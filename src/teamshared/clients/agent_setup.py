"""Agent-specific MCP setup snippets for self-service token onboarding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

KNOWN_AGENT_TYPES = frozenset({"cursor", "codex", "hermes", "claude", "openclaw"})

_REPO_RULE_MDC = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "teamshared"
    / "rules"
    / "teamshared.mdc"
)


def load_teamshared_memory_rule_mdc() -> str:
    """Load bundled ``teamshared-memory.mdc`` (plugin rule) for onboarding pages."""
    try:
        raw = resources.files("teamshared.clients").joinpath("teamshared.mdc").read_bytes()
        return raw.decode("utf-8")
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        if _REPO_RULE_MDC.is_file():
            return _REPO_RULE_MDC.read_text(encoding="utf-8")
        raise FileNotFoundError(
            "teamshared.mdc is not bundled and repo copy is missing"
        ) from None


def normalize_agent_type(value: str) -> str | None:
    """Map ``cursor-chad`` → ``cursor``; accept known types case-insensitively."""
    raw = value.strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower in KNOWN_AGENT_TYPES:
        return lower
    if "-" in lower:
        prefix = lower.split("-", 1)[0]
        if prefix in KNOWN_AGENT_TYPES:
            return prefix
    return None


@dataclass(frozen=True)
class AgentSetup:
    agent_type: str
    title: str
    config_path: str
    steps: tuple[str, ...]
    snippet: str
    snippet_lang: str
    rule_mdc: str | None = None
    rule_install_steps: tuple[str, ...] = ()


def agent_setup(agent_type: str, *, mcp_url: str, token: str) -> AgentSetup | None:
    """Return paste-ready setup for a known agent type."""
    if agent_type == "cursor":
        payload = {
            "mcpServers": {
                "teamshared": {
                    "url": mcp_url,
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        }
        rule_mdc = load_teamshared_memory_rule_mdc()
        return AgentSetup(
            agent_type=agent_type,
            title="Cursor",
            config_path="~/.cursor/rules/teamshared.mdc and ~/.cursor/mcp.json",
            steps=(
                "Copy the teamshared rule from the Memory rule section below "
                "into ~/.cursor/rules/teamshared.mdc (include the --- frontmatter lines).",
                "Open or create ~/.cursor/mcp.json and merge the JSON block below "
                "(keep any other mcpServers entries).",
                "In Cursor: Command Palette → Developer: Reload Window.",
                "Confirm teamshared appears under Settings → MCP.",
            ),
            snippet=json.dumps(payload, indent=2),
            snippet_lang="json",
            rule_mdc=rule_mdc,
            rule_install_steps=(
                "Create the rules directory if needed: mkdir -p ~/.cursor/rules",
                "Copy everything in the Memory rule block below into "
                "~/.cursor/rules/teamshared.mdc.",
                "Developer: Reload Window so Cursor loads the rule.",
            ),
        )

    if agent_type == "codex":
        snippet = (
            "# Add to ~/.codex/config.toml (token is inline; no env vars needed):\n"
            "[mcp_servers.teamshared]\n"
            f'url = "{mcp_url}"\n'
            f'http_headers = {{ Authorization = "Bearer {token}" }}\n'
            "enabled = true\n"
        )
        return AgentSetup(
            agent_type=agent_type,
            title="Codex",
            config_path="~/.codex/config.toml",
            steps=(
                "Paste the TOML block below into ~/.codex/config.toml.",
                "Run `codex mcp list` to confirm teamshared is registered.",
                "Start a new Codex session and confirm teamshared tools are available.",
            ),
            snippet=snippet,
            snippet_lang="toml",
        )

    if agent_type == "hermes":
        snippet = (
            "# Paste under mcp_servers: in ~/.hermes/config.yaml\n"
            "mcp_servers:\n"
            "  teamshared:\n"
            f"    url: {mcp_url}\n"
            "    headers:\n"
            f'      Authorization: "Bearer {token}"\n'
            "    timeout: 30\n"
            "    connect_timeout: 10\n"
        )
        return AgentSetup(
            agent_type=agent_type,
            title="Hermes",
            config_path="~/.hermes/config.yaml",
            steps=(
                "Open ~/.hermes/config.yaml.",
                "Paste the block below under mcp_servers: (merge with existing servers).",
                "Restart Hermes so it reloads MCP config.",
            ),
            snippet=snippet,
            snippet_lang="yaml",
        )

    if agent_type == "claude":
        payload = {
            "mcpServers": {
                "teamshared": {
                    "url": mcp_url,
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        }
        return AgentSetup(
            agent_type=agent_type,
            title="Claude Desktop",
            config_path="~/Library/Application Support/Claude/claude_desktop_config.json",
            steps=(
                "Open Claude Desktop config (path above on macOS; see Anthropic docs on Linux/Windows).",
                "Merge the JSON below under mcpServers.",
                "Quit and reopen Claude Desktop.",
            ),
            snippet=json.dumps(payload, indent=2),
            snippet_lang="json",
        )

    if agent_type == "openclaw":
        snippet = (
            f"openclaw config set 'mcp_servers.teamshared.url' '{mcp_url}'\n"
            f"openclaw config set 'mcp_servers.teamshared.headers.Authorization' 'Bearer {token}'\n"
            "openclaw config set 'mcp_servers.teamshared.timeout' 30\n"
            "openclaw daemon restart\n"
            "openclaw mcp list\n"
        )
        return AgentSetup(
            agent_type=agent_type,
            title="OpenClaw",
            config_path="OpenClaw config (via CLI)",
            steps=(
                "Run the commands below in your terminal (adjust if your build uses config.yaml instead).",
                "Confirm teamshared tools appear in openclaw mcp list.",
            ),
            snippet=snippet,
            snippet_lang="bash",
        )

    return None
