"""``sptx`` CLI -- the operator-facing surface.

Subcommands:

- ``sptx serve [--transport http|stdio]`` -- run the MCP server.
- ``sptx worker`` -- run the distillation worker.
- ``sptx migrate`` -- apply SQL migrations against the configured Postgres.
- ``sptx token mint <agent>`` -- issue a bearer token for an agent.
- ``sptx token list`` -- list issued tokens (prefixes only).
- ``sptx token revoke <prefix>`` -- revoke tokens by prefix.
- ``sptx config show`` -- print effective settings (secrets redacted).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import psycopg
import typer
from rich.console import Console
from rich.table import Table

from sptx.auth import TokenStore
from sptx.config import get_settings
from sptx.logging import configure_logging

app = typer.Typer(no_args_is_help=True, add_completion=False, help="sptx memory CLI")
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
    host: str | None = typer.Option(None, help="Override SPTX_HOST"),
    port: int | None = typer.Option(None, help="Override SPTX_PORT"),
) -> None:
    """Run the MCP server."""
    settings = get_settings()
    configure_logging(settings.log_level)

    if transport == "stdio":
        from sptx.server.app import _init_state, _teardown_state, build_mcp

        mcp = build_mcp(settings)

        async def _run_stdio() -> None:
            state = await _init_state(settings)
            try:
                await mcp.run_async(transport="stdio")
            finally:
                await _teardown_state(state)

        asyncio.run(_run_stdio())
        return

    if transport != "http":
        raise typer.BadParameter(f"unknown transport: {transport}")

    import uvicorn

    from sptx.server.app import build_http_app

    server_app = build_http_app(settings)
    uvicorn.run(
        server_app,
        host=host or settings.host,
        port=port or settings.port,
        log_level=settings.log_level,
    )


@app.command()
def seed(
    agent: str = typer.Option("sptx", help="Agent attribution stamped on each seed procedure"),
    force: bool = typer.Option(
        False, "--force", help="Insert a new version even if the latest already matches."
    ),
) -> None:
    """Insert (or refresh) the bundled starter procedures.

    Each procedure is checked against its latest stored version; if the body
    differs (or ``--force`` is set), a new version is inserted.
    """

    async def _run() -> None:
        from sptx.memory.procedural import ProceduralStore
        from sptx.seed.procedures import STARTER_PROCEDURES

        settings = get_settings()
        store = ProceduralStore(settings.pg_dsn)
        await store.connect()
        try:
            for name, description, steps_md, tags in STARTER_PROCEDURES:
                existing = await store.get_procedure(name)
                if existing and not force and existing.get("steps_md") == steps_md:
                    console.print(f"  [dim]unchanged[/dim] {name}")
                    continue
                proc = await store.set_procedure(
                    name,
                    steps_md,
                    agent=agent,
                    description=description,
                    tags=tags,
                )
                console.print(f"  [green]wrote[/green] {name} v{proc['version']}")
        finally:
            await store.close()

    asyncio.run(_run())


@app.command()
def worker() -> None:
    """Run the distillation worker (long-running)."""
    from sptx.distill.worker import main as worker_main

    worker_main()


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

    with psycopg.connect(settings.pg_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sptx_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        cur.execute("SELECT name FROM sptx_migrations")
        applied = {row[0] for row in cur.fetchall()}
        for path in files:
            if path.name in applied:
                console.print(f"  [dim]skip[/dim] {path.name}")
                continue
            sql = path.read_text()
            console.print(f"  [green]apply[/green] {path.name}")
            cur.execute(sql)
            cur.execute("INSERT INTO sptx_migrations (name) VALUES (%s)", (path.name,))
    console.print("[bold green]Migrations complete.[/bold green]")


@token_app.command("mint")
def token_mint(agent: str) -> None:
    """Mint a new bearer token for ``agent``.

    The raw token is printed ONCE. Copy it into the agent's MCP config; we
    can't recover it later (only a prefix is stored).
    """
    settings = get_settings()
    store = TokenStore(settings.tokens_file)
    token = store.mint(agent)
    console.print(f"[bold]agent[/bold]: {agent}")
    console.print(f"[bold]token[/bold]: [cyan]{token}[/cyan]")
    console.print(f"[dim]Stored in {settings.tokens_file}[/dim]")


@token_app.command("list")
def token_list() -> None:
    """List issued tokens (agent + prefix + created_at)."""
    settings = get_settings()
    store = TokenStore(settings.tokens_file)
    entries = store.list_agents()
    table = Table(title="sptx tokens")
    table.add_column("agent")
    table.add_column("token (prefix)")
    table.add_column("created_at")
    for entry in entries:
        table.add_row(entry["agent"], entry["token_prefix"], entry["created_at"])
    console.print(table)


@token_app.command("revoke")
def token_revoke(prefix: str) -> None:
    """Revoke all tokens starting with ``prefix`` (min 8 chars)."""
    if len(prefix) < 8:
        raise typer.BadParameter("prefix must be at least 8 characters")
    settings = get_settings()
    store = TokenStore(settings.tokens_file)
    n = store.revoke(prefix)
    console.print(f"[bold]revoked[/bold]: {n}")


@config_app.command("show")
def config_show() -> None:
    """Print effective configuration. Secret-ish fields are redacted."""
    settings = get_settings()
    redacted = {"pg_password", "neo4j_password"}
    data: dict[str, Any] = {}
    for k, v in settings.model_dump().items():
        if k in redacted and v:
            data[k] = "***"
        else:
            data[k] = v
    table = Table(title="sptx config")
    table.add_column("key")
    table.add_column("value")
    for k in sorted(data):
        table.add_row(k, str(data[k]))
    console.print(table)


if __name__ == "__main__":
    app()
