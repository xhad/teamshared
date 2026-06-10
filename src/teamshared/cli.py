"""``teamshared`` CLI -- the operator-facing surface.

Subcommands:

- ``teamshared serve [--transport http|stdio]`` -- run the MCP server.
- ``teamshared worker`` -- run the distillation worker.
- ``teamshared curator`` -- run the wiki curation worker.
- ``teamshared migrate`` -- apply SQL migrations against the configured Postgres.
- ``teamshared token mint <agent>`` -- issue a bearer token for an agent.
- ``teamshared token invite-create [--agent] [--uses]`` -- create a one-time invite code.
- ``teamshared token invite-list`` -- list active invite codes.
- ``teamshared config show`` -- print effective settings (secrets redacted).
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import psycopg
import typer
from psycopg import sql
from rich.console import Console
from rich.table import Table

from teamshared.clients.agent_setup import normalize_agent_type
from teamshared.config import get_settings
from teamshared.config_validate import validate_settings
from teamshared.identity.agent_tokens import AgentTokenMinter
from teamshared.identity.legacy_bridge import PrincipalResolver
from teamshared.invite import InviteStore
from teamshared.logging import configure_logging
from teamshared.server.services import make_services
from teamshared.server.token_api import get_token_path, invite_redeem_curl, invite_redeem_url

app = typer.Typer(no_args_is_help=True, add_completion=False, help="teamshared memory CLI")
token_app = typer.Typer(no_args_is_help=True, help="Bearer-token management")
config_app = typer.Typer(no_args_is_help=True, help="Inspect runtime configuration")
app.add_typer(token_app, name="token")
app.add_typer(config_app, name="config")

console = Console()


@app.command()
def serve(
    transport: str = typer.Option(
        "http",
        "--transport",
        "-t",
        help="MCP transport: 'http' (streamable HTTP) or 'stdio' (local debugging).",
    ),
    host: str | None = typer.Option(None, help="Override TEAMSHARED_HOST"),
    port: int | None = typer.Option(None, help="Override TEAMSHARED_PORT"),
) -> None:
    """Run the MCP server."""
    settings = get_settings()
    validate_settings(settings)
    configure_logging(settings.log_level)

    if transport == "stdio":
        from teamshared.identity.legacy_bridge import PrincipalResolver
        from teamshared.server.app import _init_state, _teardown_state, build_mcp
        from teamshared.server.services import make_services

        mcp = build_mcp(settings)

        async def _run_stdio() -> None:
            services = make_services(settings)
            resolver = PrincipalResolver(
                api_keys=services.api_keys,
                roles=services.roles,
                tenant_db=services.tenant_db,
                default_org_id=settings.default_org_id,
                session_secret=settings.session_secret,
            )
            state = await _init_state(settings, services, resolver)
            try:
                await mcp.run_async(transport="stdio")
            finally:
                await _teardown_state(state)

        asyncio.run(_run_stdio())
        return

    if transport != "http":
        raise typer.BadParameter(f"unknown transport: {transport}")

    import uvicorn

    from teamshared.server.app import build_http_app

    server_app = build_http_app(settings)
    uvicorn.run(
        server_app,
        host=host or settings.host,
        port=port or settings.port,
        log_level=settings.log_level,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


@app.command()
def seed(
    agent: str = typer.Option("teamshared", help="Agent attribution stamped on each seed procedure"),
    force: bool = typer.Option(
        False, "--force", help="Insert a new version even if the latest already matches."
    ),
) -> None:
    """Insert (or refresh) the bundled starter procedures.

    Each procedure is checked against its latest stored version; if the body
    differs (or ``--force`` is set), a new version is inserted.
    """

    async def _run() -> None:
        from teamshared.memory.procedural import OrgProceduralStore
        from teamshared.seed.procedures import STARTER_PROCEDURES
        from teamshared.tenancy.context import TenantDb

        settings = get_settings()
        org_id = settings.default_org_id
        db = TenantDb(settings.pg_app_dsn)
        await db.connect()
        store = OrgProceduralStore(db)
        try:
            for name, description, steps_md, tags in STARTER_PROCEDURES:
                existing = await store.get_procedure(org_id, name)
                if existing and not force and existing.get("steps_md") == steps_md:
                    console.print(f"  [dim]unchanged[/dim] {name}")
                    continue
                proc = await store.set_procedure(
                    org_id,
                    name,
                    steps_md,
                    agent=agent,
                    description=description,
                    tags=tags,
                )
                console.print(f"  [green]wrote[/green] {name} v{proc['version']}")
        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def worker() -> None:
    """Run the distillation worker (long-running)."""
    from teamshared.distill.worker import main as worker_main

    worker_main()


@app.command()
def curator() -> None:
    """Run the wiki curation worker (long-running)."""
    from teamshared.distill.curator_worker import main as curator_main

    curator_main()


@app.command()
def migrate(
    migrations_dir: Path = typer.Option(
        Path("infra/migrations"),
        help="Directory containing ``NNN_*.sql`` files (applied in lexical order).",
    ),
) -> None:
    """Apply SQL migrations against the configured Postgres."""
    settings = get_settings()
    configure_logging(settings.log_level)

    files = sorted(p for p in migrations_dir.glob("*.sql"))
    if not files:
        console.print(f"[yellow]No migrations found in {migrations_dir}[/yellow]")
        raise typer.Exit(code=1)

    # Each migration runs in its own transaction: a failure rolls the file back
    # and aborts the run instead of leaving a partially-applied schema. A sha256
    # checksum is recorded per file so edits to an already-applied migration are
    # detected and rejected (add a new migration instead).
    with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS teamshared_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        cur.execute("ALTER TABLE teamshared_migrations ADD COLUMN IF NOT EXISTS checksum TEXT")
        conn.commit()
        cur.execute("SELECT name, checksum FROM teamshared_migrations")
        applied: dict[str, str | None] = {row[0]: row[1] for row in cur.fetchall()}
        for path in files:
            sql_text = path.read_text()
            digest = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
            if path.name in applied:
                stored = applied[path.name]
                if stored is None:
                    # Applied before checksums existed: backfill from disk.
                    cur.execute(
                        "UPDATE teamshared_migrations SET checksum = %s WHERE name = %s",
                        (digest, path.name),
                    )
                    conn.commit()
                    console.print(f"  [dim]skip[/dim] {path.name} [dim](checksum recorded)[/dim]")
                elif stored != digest:
                    console.print(
                        f"  [bold red]checksum mismatch[/bold red] {path.name}: the file "
                        "changed after it was applied. Never edit an applied migration; "
                        "add a new one."
                    )
                    raise typer.Exit(code=1)
                else:
                    console.print(f"  [dim]skip[/dim] {path.name}")
                continue
            console.print(f"  [green]apply[/green] {path.name}")
            try:
                cur.execute(sql_text)
                cur.execute(
                    "INSERT INTO teamshared_migrations (name, checksum) VALUES (%s, %s)",
                    (path.name, digest),
                )
            except Exception as exc:
                conn.rollback()
                console.print(
                    f"  [bold red]failed[/bold red] {path.name}: {exc}\n"
                    "  Rolled back; no partial schema was left behind."
                )
                raise typer.Exit(code=1) from exc
            conn.commit()
    console.print("[bold green]Migrations complete.[/bold green]")


@app.command("provision-app-role")
def provision_app_role() -> None:
    """Create/refresh the non-superuser ``teamshared_app`` login role.

    RLS is only a real boundary when the application connects as a role that
    is neither a superuser nor ``BYPASSRLS``. This creates that role with the
    password from ``TEAMSHARED_PG_APP_PASSWORD`` and grants it CRUD on the
    current schema. Run it as an admin (after ``migrate``).
    """
    settings = get_settings()
    if not settings.pg_app_user or not settings.pg_app_password:
        raise typer.BadParameter(
            "Set TEAMSHARED_PG_APP_USER and TEAMSHARED_PG_APP_PASSWORD first."
        )
    role = settings.pg_app_user
    with psycopg.connect(settings.pg_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        exists = cur.fetchone() is not None
        # Role DDL cannot bind parameters for PASSWORD; compose a safe literal.
        verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
        cur.execute(
            sql.SQL("{verb} {role} WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {pw}").format(
                verb=verb,
                role=sql.Identifier(role),
                pw=sql.Literal(settings.pg_app_password),
            )
        )
        cur.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        cur.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'
        )
        cur.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cur.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"'
        )
        cur.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            f'GRANT USAGE, SELECT ON SEQUENCES TO "{role}"'
        )
        for fn in ("auth_lookup_api_key(text)", "auth_touch_api_key(uuid)",
                   "provision_organization(text, text)",
                   "provision_account(text, text)", "auth_account_orgs(text)"):
            cur.execute(f'GRANT EXECUTE ON FUNCTION {fn} TO "{role}"')
    console.print(f"[bold green]Provisioned app role[/bold green] {role}")


@app.command("verify-rls")
def verify_rls() -> None:
    """Assert tenant isolation: a query with no org context returns zero rows.

    Connects as the application role and confirms ``memory_items`` is empty
    without ``app.current_org_id`` set. Exits non-zero if any row leaks.
    """
    settings = get_settings()
    leaked = 0
    with psycopg.connect(settings.pg_app_dsn) as conn, conn.cursor() as cur:
        for table in ("memory_items", "users", "audit_events", "connectors"):
            cur.execute(f"SELECT count(*) FROM {table}")
            row = cur.fetchone()
            count = int(row[0]) if row else 0
            if count:
                console.print(f"[red]LEAK[/red] {table}: {count} rows visible without org context")
                leaked += count
            else:
                console.print(f"  [green]ok[/green] {table}: 0 rows without org context")
    if leaked:
        console.print("[bold red]RLS verification FAILED[/bold red]")
        raise typer.Exit(code=1)
    console.print("[bold green]RLS verification passed.[/bold green]")


@app.command("backfill-mem0")
def backfill_mem0(
    limit: int = typer.Option(0, "--limit", help="Max rows to backfill (0 = all)."),
    agent_fallback: str = typer.Option(
        "unknown", help="Agent attribution for rows missing a user_id."
    ),
) -> None:
    """Re-ingest existing Mem0 memories into ``memory_items`` under the default org.

    G2 moves recall onto pgvector + RLS. Existing Mem0 rows (the live brain)
    are invisible to the new path until copied across. This reads the Mem0
    collection's ``payload`` JSONB and re-ingests each row through the
    org-scoped ingestion pipeline (dedup makes it safe to re-run). Run it once
    before relying on the converged recall path.
    """

    async def _run() -> None:
        from typing import cast

        from teamshared.identity.legacy_bridge import PrincipalResolver
        from teamshared.memory.request_context import RequestContext
        from teamshared.memory.types import MemoryKind
        from teamshared.server.services import make_services

        settings = get_settings()
        org_id = settings.default_org_id
        table = settings.mem0_collection

        select = (
            "SELECT id, COALESCE(payload->>'data', payload->>'memory', payload->>'text'), "
            "payload->>'user_id', payload->>'pillar', payload->>'kind', "
            f'payload->>\'subject\', payload->\'tags\' FROM "{table}"'
        )
        if limit > 0:
            select += f" LIMIT {int(limit)}"

        rows: list[tuple[Any, ...]] = []
        with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
            cur.execute(select)
            rows = list(cur.fetchall())

        services = make_services(settings)
        resolver = PrincipalResolver(
            api_keys=services.api_keys,
            roles=services.roles,
            tenant_db=services.tenant_db,
            default_org_id=org_id,
            session_secret=settings.session_secret,
        )
        await services.tenant_db.connect()
        ingestion = services.ingestion()
        ingested = skipped = 0
        try:
            for _rid, content, user_id, pillar, kind, subject, tags in rows:
                text = (content or "").strip()
                if not text:
                    skipped += 1
                    continue
                agent = user_id or agent_fallback
                principal = await resolver.agent_principal(org_id, agent)
                ctx = RequestContext(
                    principal=principal,
                    db=services.tenant_db,
                    authorizer=services.authorizer(),
                )
                memory_kind: MemoryKind = cast(
                    MemoryKind,
                    kind if kind in {"fact", "preference", "event", "note"} else "note",
                )
                memory_pillar = pillar if pillar in {"semantic", "episodic"} else "semantic"
                result = await ingestion.ingest(
                    ctx, text, kind=memory_kind, pillar=memory_pillar, scope="org",
                    subject=subject, tags=list(tags) if tags else None, source="agent",
                )
                if result.status == "duplicate":
                    skipped += 1
                else:
                    ingested += 1
        finally:
            await services.tenant_db.close()
        console.print(
            f"[bold green]Backfill complete[/bold green]: {ingested} ingested, {skipped} skipped "
            f"({len(rows)} scanned)"
        )

    asyncio.run(_run())


@app.command("provision-default-org")
def provision_default_org(
    email: str | None = typer.Option(
        None, "--email", help="Owner email (defaults to TEAMSHARED_DASHBOARD_OWNER_EMAIL)."
    ),
) -> None:
    """Seed the default org's owner user + membership + role for /app console login.

    The default org itself is created by migration 010. This adds the owner
    user (idempotent) so the magic-link dashboard has someone to sign in.
    """

    async def _run() -> None:
        from teamshared.identity.roles import RoleStore
        from teamshared.tenancy.context import TenantDb

        settings = get_settings()
        owner_email = email or settings.dashboard_owner_email
        if not owner_email:
            raise typer.BadParameter(
                "Provide --email or set TEAMSHARED_DASHBOARD_OWNER_EMAIL."
            )
        org_id = settings.default_org_id
        db = TenantDb(settings.pg_app_dsn)
        await db.connect()
        roles = RoleStore(db)
        try:
            async with db.org(org_id) as conn:
                cur = await conn.execute(
                    "INSERT INTO users (org_id, email, status) VALUES (%s, %s, 'active') "
                    "ON CONFLICT (org_id, email) DO UPDATE SET status = 'active' RETURNING id",
                    (str(org_id), owner_email),
                )
                row = await cur.fetchone()
                assert row is not None
                user_id = row[0]
                await conn.execute(
                    "INSERT INTO memberships (org_id, user_id, role) VALUES (%s, %s, 'org_owner') "
                    "ON CONFLICT (org_id, user_id) DO UPDATE SET role = 'org_owner'",
                    (str(org_id), str(user_id)),
                )
            await roles.bind_role(
                org_id=org_id, principal_type="user", principal_id=user_id, role_name="org_owner"
            )
        finally:
            await db.close()
        console.print(
            f"[bold green]Provisioned default-org owner[/bold green]: {owner_email} ({user_id})"
        )

    asyncio.run(_run())


@token_app.command("mint")
def token_mint(
    agent: str = typer.Argument(..., help="Agent type: cursor, codex, hermes, claude, or openclaw."),
) -> None:
    """Mint a new ``tsk_`` API key for ``agent`` in the default org.

    The raw token is printed ONCE. Copy it into the agent's MCP config; only a
    hash is stored in Postgres.
    """
    agent_type = normalize_agent_type(agent)
    if agent_type is None:
        raise typer.BadParameter("agent must be one of: cursor, codex, hermes, claude, openclaw")

    async def _run() -> None:
        settings = get_settings()
        services = make_services(settings)
        await services.tenant_db.connect()
        try:
            resolver = PrincipalResolver(
                api_keys=services.api_keys,
                roles=services.roles,
                tenant_db=services.tenant_db,
                default_org_id=settings.default_org_id,
                session_secret=settings.session_secret,
            )
            minter = AgentTokenMinter(
                api_keys=services.api_keys,
                resolver=resolver,
                org_id=settings.default_org_id,
            )
            _, token = await minter.mint(agent_type)
            console.print(f"[bold]agent[/bold]: {agent_type}")
            console.print(f"[bold]token[/bold]: [cyan]{token}[/cyan]")
            console.print("[dim]Org-scoped tsk_ API key (Postgres).[/dim]")
        finally:
            await services.tenant_db.close()

    asyncio.run(_run())


@token_app.command("invite-create")
def token_invite_create(
    agent: str | None = typer.Option(
        None,
        "--agent",
        "-a",
        help="Agent type for this invite: cursor, codex, hermes, claude, or openclaw.",
    ),
    uses: int = typer.Option(1, "--uses", "-n", help="Number of redemptions allowed."),
) -> None:
    """Create a one-time invite code for self-service token minting."""
    if uses <= 0:
        raise typer.BadParameter("uses must be positive")
    agent_type: str | None = None
    if agent is not None:
        agent_type = normalize_agent_type(agent)
        if agent_type is None:
            raise typer.BadParameter("agent must be one of: cursor, codex, hermes, claude, openclaw")
    settings = get_settings()
    invites = InviteStore(settings.invites_file)
    record = invites.create(agent=agent_type, uses=uses)
    console.print(f"[bold]invite[/bold]: [cyan]{record.code}[/cyan]")
    if record.agent:
        console.print(f"[bold]agent[/bold]: {record.agent}")
    console.print(f"[bold]uses[/bold]: {record.uses_left}")
    base = settings.public_url
    if base:
        root = base.rstrip("/")
        if record.agent:
            link = f"{root}{get_token_path(record.code, record.agent)}"
            curl = invite_redeem_curl(root, record.code, record.agent)
            root_url = invite_redeem_url(root, record.code, record.agent)
        else:
            link = f"{root}{get_token_path(record.code)}"
            curl = invite_redeem_curl(root, record.code, "<agent>")
            root_url = None
        console.print(f"[bold]link[/bold]: {link}")
        console.print(f"[bold]curl[/bold]: {curl}")
        if root_url:
            console.print(f"[bold]url[/bold]: {root_url}")
    else:
        console.print(
            "[dim]Set TEAMSHARED_PUBLIC_URL to print a shareable /get-token link.[/dim]"
        )


@token_app.command("invite-list")
def token_invite_list() -> None:
    """List active invite codes."""
    settings = get_settings()
    invites = InviteStore(settings.invites_file)
    rows = invites.list_invites()
    table = Table(title="teamshared invites")
    table.add_column("code")
    table.add_column("agent")
    table.add_column("uses_left")
    table.add_column("created_at")
    for row in rows:
        table.add_row(
            row.code,
            row.agent or "",
            str(row.uses_left),
            row.created_at,
        )
    console.print(table)


@config_app.command("show")
def config_show() -> None:
    """Print effective configuration. Secret-ish fields are redacted."""
    settings = get_settings()
    redacted = {"pg_password", "neo4j_password", "mint_secret"}
    data: dict[str, Any] = {}
    for k, v in settings.model_dump().items():
        if k in redacted and v:
            data[k] = "***"
        else:
            data[k] = v
    table = Table(title="teamshared config")
    table.add_column("key")
    table.add_column("value")
    for k in sorted(data):
        table.add_row(k, str(data[k]))
    console.print(table)


if __name__ == "__main__":
    app()
