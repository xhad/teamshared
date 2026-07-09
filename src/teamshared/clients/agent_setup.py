"""Agent-specific MCP setup snippets for self-service token onboarding."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

KNOWN_AGENT_TYPES = frozenset({"cursor", "codex", "hermes", "claude", "openclaw", "pi"})

# Fallback when the rule markdown carries no parseable ``version:`` marker.
RULE_VERSION_FALLBACK = "0.0.0"

_RULE_VERSION_RE = re.compile(
    r"^\s*(?:#\s*)?version:\s*([0-9]+(?:\.[0-9]+){1,2}[0-9A-Za-z.\-]*)\s*$",
    re.MULTILINE,
)

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


def parse_rule_version(rule_md: str) -> str:
    """Extract the ``version:`` marker from rule markdown (frontmatter or body)."""
    match = _RULE_VERSION_RE.search(rule_md)
    return match.group(1) if match else RULE_VERSION_FALLBACK


def teamshared_rule_version() -> str:
    """Version of the canonical ``teamshared.mdc`` rule the server ships."""
    try:
        return parse_rule_version(load_teamshared_memory_rule_mdc())
    except FileNotFoundError:
        return RULE_VERSION_FALLBACK


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
                "From anywhere, run: curl -fsSL <server>/install.sh | bash",
                "Or copy the teamshared rule into ~/.cursor/rules/teamshared.mdc.",
                "Merge the JSON block below into ~/.cursor/mcp.json.",
                "~/.cursor/mcp.json is outside any repo; keep it private (bearer token).",
                "Command Palette → Developer: Reload Window.",
            ),
            snippet=json.dumps(payload, indent=2),
            snippet_lang="json",
            rule_mdc=rule_mdc,
            rule_install_steps=(
                "mkdir -p ~/.cursor/rules",
                "Copy the Memory rule block into ~/.cursor/rules/teamshared.mdc.",
                "Developer: Reload Window so Cursor loads the rule.",
            ),
        )

    if agent_type == "codex":
        snippet = (
            "# Add to ./.codex/config.toml in your project root:\n"
            "[mcp_servers.teamshared]\n"
            f'url = "{mcp_url}"\n'
            f'http_headers = {{ Authorization = "Bearer {token}" }}\n'
            "enabled = true\n"
        )
        return AgentSetup(
            agent_type=agent_type,
            title="Codex",
            config_path="./.codex/config.toml",
            steps=(
                "From project root: curl -fsSL <server>/install.sh | bash",
                "Or paste the TOML block below into ./.codex/config.toml.",
                "Run Codex from the project root so it loads ./.codex/config.toml.",
                "Run `codex mcp list` to confirm teamshared is registered.",
            ),
            snippet=snippet,
            snippet_lang="toml",
        )

    if agent_type == "hermes":
        snippet = (
            "# Paste under mcp_servers: in ./.hermes/config.yaml\n"
            "# Protocol: ./.hermes/teamshared-protocol.md (merge into SOUL if needed)\n"
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
            config_path="./.hermes/config.yaml",
            steps=(
                "From project root: curl -fsSL <server>/install.sh | bash",
                "Or paste the block below under mcp_servers: in ./.hermes/config.yaml.",
                "Restart Hermes from the project root.",
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
            config_path="./.claude/claude_desktop_config.json",
            steps=(
                "From project root: curl -fsSL <server>/install.sh | bash",
                "Or merge the JSON below into ./.claude/claude_desktop_config.json.",
                "Point Claude Desktop at that file or merge into your global config.",
                "Add .claude/ to .gitignore if it holds your bearer token.",
            ),
            snippet=json.dumps(payload, indent=2),
            snippet_lang="json",
        )

    if agent_type == "openclaw":
        snippet = (
            f"# Project-local fragment: ./.openclaw/teamshared-mcp.yaml\n"
            f"# Or run from project root: curl -fsSL <server>/install.sh | bash\n"
            "mcp_servers:\n"
            "  teamshared:\n"
            f"    url: {mcp_url}\n"
            "    headers:\n"
            f'      Authorization: "Bearer {token}"\n'
            "    timeout: 30\n"
        )
        return AgentSetup(
            agent_type=agent_type,
            title="OpenClaw",
            config_path="./.openclaw/teamshared-mcp.yaml",
            steps=(
                "From project root: curl -fsSL <server>/install.sh | bash",
                "Merge ./.openclaw/teamshared-mcp.yaml into your OpenClaw config.",
                "Confirm teamshared tools appear in openclaw mcp list.",
            ),
            snippet=snippet,
            snippet_lang="bash",
        )

    if agent_type == "pi":
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
            title="Pi",
            config_path="./.mcp.json",
            steps=(
                "From project root: curl -fsSL <server>/install.sh | bash",
                "Install the MCP adapter if needed: pi install npm:pi-mcp-adapter",
                "Or merge the JSON block below into ./.mcp.json in your project root.",
                "Run pi from the project root and use /mcp to verify teamshared is connected.",
                "Add .mcp.json to .gitignore if it holds your bearer token.",
            ),
            snippet=json.dumps(payload, indent=2),
            snippet_lang="json",
        )

    return None
