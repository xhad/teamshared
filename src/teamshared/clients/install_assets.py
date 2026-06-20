"""Resolve install assets from the teamshared plugin bundle (single source of truth).

Layout under ``plugins/teamshared/``:

- ``rules/`` — canonical ``teamshared.mdc`` / ``teamshared.md`` memory rules
- ``clients/`` — copy-paste protocol and reference snippets for humans
- ``install/`` — harness templates served at ``/install/assets/*`` (placeholders)
- ``hooks/``, ``skills/``, … — Cursor marketplace plugin components
"""

from __future__ import annotations

from pathlib import Path

PLUGIN_BUNDLE_PATH = Path("/app/plugins/teamshared")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_PLUGIN = _REPO_ROOT / "plugins" / "teamshared"

# URL path under /install/assets/ → path relative to plugin root.
_ASSET_ALIASES: dict[str, str] = {
    "cursor/teamshared.mdc": "rules/teamshared.mdc",
    "hermes/protocol.md": "clients/protocol.md",
}


def plugin_root() -> Path | None:
    """Plugin bundle directory (Docker or repo checkout)."""
    if PLUGIN_BUNDLE_PATH.is_dir():
        return PLUGIN_BUNDLE_PATH
    if _REPO_PLUGIN.is_dir():
        return _REPO_PLUGIN
    return None


def install_dir() -> Path | None:
    """``plugins/teamshared/install`` — harness templates for curl install."""
    root = plugin_root()
    if root is None:
        return None
    path = root / "install"
    return path if path.is_dir() else None


def resolve_install_asset(rel: str) -> Path | None:
    """Map ``/install/assets/{rel}`` to a file under the plugin bundle."""
    rel = rel.lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None

    root = plugin_root()
    if root is None:
        return None

    alias = _ASSET_ALIASES.get(rel)
    if alias is not None:
        path = (root / alias).resolve()
        if str(path).startswith(str(root.resolve())) and path.is_file():
            return path
        return None

    install = install_dir()
    if install is None:
        return None
    path = (install / rel).resolve()
    if not str(path).startswith(str(install.resolve())):
        return None
    return path if path.is_file() else None
