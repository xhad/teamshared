"""Unified curl-pipe-bash installer served at ``/install.sh``."""

from __future__ import annotations

from teamshared.clients.agent_setup import KNOWN_AGENT_TYPES

PLUGIN_BUNDLE_PATH = "/app/plugins/teamshared"
INSTALL_ASSETS_PATH = "/app/install_assets"
_REPO_PLUGIN = None  # set lazily in install_api
_REPO_ASSETS = None

# Placeholders substituted when the script is served (request base URL).
_INSTALL_SH = r"""#!/usr/bin/env bash
# teamshared unified installer
#   curl -fsSL __BASE__/install.sh | bash
set -euo pipefail

TEAMSHARED_BASE_URL="${TEAMSHARED_BASE_URL:-__BASE__}"
TEAMSHARED_MCP_URL="${TEAMSHARED_MCP_URL:-__MCP_URL__}"
ASSETS="${TEAMSHARED_BASE_URL}/install/assets"

_ts_die() { echo "teamshared install: $*" >&2; exit 1; }

_ts_need_cmd() {
  command -v "$1" >/dev/null 2>&1 || _ts_die "missing required command: $1"
}

_ts_fetch() {
  local dest="$1"
  local url="$2"
  mkdir -p "$(dirname "$dest")"
  curl -fsSL "$url" -o "$dest"
}

# curl | bash has no stdin TTY; read prompts from the controlling terminal.
_ts_tty() {
  if [[ -t 0 ]]; then
    printf '%s' "$1"
  elif [[ -r /dev/tty ]]; then
    printf '%s' "$1" >/dev/tty
  else
    _ts_die "no terminal available for prompts (try: bash install-teamshared.sh)"
  fi
}

_ts_read() {
  if [[ -t 0 ]]; then
    read -r "$@"
  else
    read -r "$@" </dev/tty
  fi
}

_ts_read_secret() {
  if [[ -t 0 ]]; then
    read -rs "$@"
    echo
  else
    read -rs "$@" </dev/tty
    echo >/dev/tty
  fi
}

_ts_choose_harness() {
  _ts_tty $'\nSelect agent harness:\n  1) cursor   — Cursor IDE (plugin, rules, MCP)\n  2) codex    — OpenAI Codex CLI\n  3) hermes   — Hermes\n  4) claude   — Claude Desktop\n  5) openclaw — OpenClaw\n\n'
  local choice
  while true; do
    _ts_tty 'Enter choice [1-5]: '
    _ts_read choice
    case "$choice" in
      1|cursor) HARNESS=cursor; break ;;
      2|codex) HARNESS=codex; break ;;
      3|hermes) HARNESS=hermes; break ;;
      4|claude) HARNESS=claude; break ;;
      5|openclaw) HARNESS=openclaw; break ;;
      *)
        _ts_tty 'Invalid choice. Enter 1, 2, 3, 4, or 5.\n'
        ;;
    esac
  done
  _ts_tty "Selected: ${HARNESS}\n"
}

_ts_prompt_token() {
  _ts_tty $'\nPaste your teamshared bearer token (from '"${TEAMSHARED_BASE_URL}"'/get-token): '
  _ts_read_secret TEAMSHARED_TOKEN
  export TEAMSHARED_TOKEN
  [[ -n "${TEAMSHARED_TOKEN}" ]] || _ts_die "empty token"
  [[ "${TEAMSHARED_TOKEN}" == teamshared_* ]] || _ts_die "token should start with teamshared_"
}

_ts_apply_token() {
  local file="$1"
  _ts_need_cmd python3
  python3 - "$file" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
token = os.environ["TEAMSHARED_TOKEN"]
text = path.read_text(encoding="utf-8")
text = text.replace("__TEAMSHARED_TOKEN__", token)
path.write_text(text, encoding="utf-8")
PY
}

_ts_merge_json_mcp() {
  local snippet_path="$1"
  local config_path="$2"
  _ts_need_cmd python3
  TEAMSHARED_SNIPPET="${snippet_path}" TEAMSHARED_CONFIG="${config_path}" python3 <<'PY'
import json
import os
from pathlib import Path

snippet_path = Path(os.environ["TEAMSHARED_SNIPPET"])
config_path = Path(os.environ["TEAMSHARED_CONFIG"])
token = os.environ["TEAMSHARED_TOKEN"]
patch = json.loads(snippet_path.read_text(encoding="utf-8"))
entry = patch.get("mcpServers", {}).get("teamshared")
if not entry:
    raise SystemExit("invalid snippet")
headers = entry.setdefault("headers", {})
headers["Authorization"] = f"Bearer {token}"

if config_path.is_file():
    data = json.loads(config_path.read_text(encoding="utf-8"))
else:
    data = {}
servers = data.setdefault("mcpServers", {})
servers["teamshared"] = entry
config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(config_path)
PY
}

_ts_finish() {
  echo ""
  case "${HARNESS}" in
    cursor)   echo "Done. Restart Cursor: Command Palette → Developer: Reload Window." ;;
    codex)    echo "Done. Restart the Codex CLI session to load the teamshared MCP server." ;;
    hermes)   echo "Done. Restart Hermes to load the teamshared MCP server." ;;
    claude)   echo "Done. Quit and reopen Claude Desktop to load the teamshared MCP server." ;;
    openclaw) echo "Done. Restart the OpenClaw daemon (openclaw daemon restart) if it was not restarted above." ;;
    *)        echo "Done. Restart your agent to load the teamshared MCP server." ;;
  esac
  echo "MCP URL: ${TEAMSHARED_MCP_URL}"
}

_ts_install_cursor() {
  _ts_need_cmd curl
  local plugin_dir="${HOME}/.cursor/plugins/local/teamshared"
  local rule_path="${HOME}/.cursor/rules/teamshared.mdc"
  local bundle_url="${TEAMSHARED_BASE_URL}/install/plugin/teamshared.tar.gz"

  echo "Installing Cursor plugin → ${plugin_dir}"
  local tmpdir
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "${tmpdir}"' RETURN
  curl -fsSL "${bundle_url}" | tar -xzf - -C "${tmpdir}"
  local root
  root="$(find "${tmpdir}" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [[ -n "${root}" ]] || _ts_die "plugin bundle layout unexpected"
  rm -rf "${plugin_dir}"
  mkdir -p "$(dirname "${plugin_dir}")"
  cp -a "${root}" "${plugin_dir}"

  mkdir -p "$(dirname "${rule_path}")"
  if [[ -f "${plugin_dir}/rules/teamshared.mdc" ]]; then
    cp "${plugin_dir}/rules/teamshared.mdc" "${rule_path}"
    echo "  rule → ${rule_path}"
  fi
  echo "  plugin → ${plugin_dir}"

  local mcp_snippet="${HOME}/.config/teamshared/cursor-mcp.json"
  local mcp_config="${HOME}/.cursor/mcp.json"
  mkdir -p "$(dirname "${mcp_snippet}")"
  _ts_fetch "${mcp_snippet}" "${ASSETS}/cursor/mcp.json"
  _ts_apply_token "${mcp_snippet}"
  _ts_merge_json_mcp "${mcp_snippet}" "${mcp_config}"
  echo "  MCP config → ${mcp_config}"
  echo ""
  echo "Optional: install Bun (https://bun.sh) for continual-learning hooks."
}

_ts_install_codex() {
  _ts_need_cmd curl
  local dest="${HOME}/.codex/config.toml"
  local snippet="${HOME}/.codex/teamshared-mcp.toml"
  mkdir -p "${HOME}/.codex"
  _ts_fetch "${snippet}" "${ASSETS}/codex/mcp.toml"
  _ts_apply_token "${snippet}"

  if [[ -f "${dest}" ]] && grep -q '\[mcp_servers.teamshared\]' "${dest}"; then
    echo "teamshared already in ${dest} — edit it manually if the token changed."
  elif [[ -f "${dest}" ]]; then
    printf '\n' >>"${dest}"
    cat "${snippet}" >>"${dest}"
    echo "Appended teamshared block → ${dest}"
  else
    cp "${snippet}" "${dest}"
    echo "Wrote ${dest}"
  fi
  echo "  snippet kept at ${snippet}"
}

_ts_install_hermes() {
  _ts_need_cmd curl
  local dest="${HOME}/.hermes/config.yaml"
  local snippet="${HOME}/.hermes/teamshared-mcp.yaml"
  mkdir -p "${HOME}/.hermes"
  _ts_fetch "${snippet}" "${ASSETS}/hermes/mcp.yaml"
  _ts_apply_token "${snippet}"

  if [[ -f "${dest}" ]] && grep -q 'teamshared:' "${dest}"; then
    _ts_need_cmd python3
    python3 - "${dest}" <<'PY'
import os, re, sys
from pathlib import Path
path = Path(sys.argv[1])
token = os.environ["TEAMSHARED_TOKEN"]
text = path.read_text(encoding="utf-8")
block = re.search(
    r"(?ms)^(\s*)teamshared:.*?^(\s*\w|\s*$)",
    text,
)
if block:
    start, end = block.span()
    indent = block.group(1)
    replacement = (
        f"{indent}teamshared:\n"
        f"{indent}  url: {os.environ['TEAMSHARED_MCP_URL']}\n"
        f"{indent}  headers:\n"
        f'{indent}    Authorization: "Bearer {token}"\n'
        f"{indent}  timeout: 30\n"
        f"{indent}  connect_timeout: 10\n"
    )
    text = text[:start] + replacement + text[end:]
    path.write_text(text, encoding="utf-8")
print(path)
PY
    echo "Updated teamshared token in ${dest}"
    echo "teamshared already in ${dest}"
  elif [[ -f "${dest}" ]]; then
    printf '\nmcp_servers:\n' >>"${dest}"
    cat "${snippet}" >>"${dest}"
    echo "Merged teamshared → ${dest}"
  else
    printf 'mcp_servers:\n' >"${dest}"
    cat "${snippet}" >>"${dest}"
    echo "Wrote ${dest}"
  fi
  _ts_fetch "${HOME}/.hermes/teamshared-protocol.md" "${ASSETS}/hermes/protocol.md" 2>/dev/null || true
  echo "  snippet → ${snippet}"

  _ts_install_hermes_hook "${dest}"
}

# Deploy the conversation-capture shell hook and register it on post_llm_call.
_ts_install_hermes_hook() {
  local config_path="$1"
  local hook_dir="${HOME}/.hermes/agent-hooks"
  local hook_script="${hook_dir}/teamshared-capture.py"
  local hook_creds="${hook_dir}/teamshared-capture.json"
  mkdir -p "${hook_dir}"

  _ts_fetch "${hook_script}" "${ASSETS}/hermes/capture.py"
  chmod +x "${hook_script}" 2>/dev/null || true

  # Credentials the stdlib hook reads (avoids parsing YAML at runtime). The
  # base URL is the origin, not the /mcp endpoint.
  python3 - "${hook_creds}" <<PY
import json, sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {"base_url": "${TEAMSHARED_BASE_URL}", "token": "${TEAMSHARED_TOKEN}"},
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
  chmod 600 "${hook_creds}" 2>/dev/null || true
  echo "  capture hook → ${hook_script}"

  if [[ -f "${config_path}" ]] && grep -q '^hooks:' "${config_path}"; then
    echo "  hooks: block already in ${config_path} — add post_llm_call manually:"
    echo "      python3 ${hook_script}"
  else
    {
      printf '\nhooks:\n'
      printf '  post_llm_call:\n'
      printf '    - command: "python3 %s"\n' "${hook_script}"
      printf '      timeout: 15\n'
    } >>"${config_path}"
    echo "  registered post_llm_call hook → ${config_path}"
  fi
  echo "  NOTE: approve the hook once with 'hermes --accept-hooks chat' (or set"
  echo "        hooks_auto_accept: true). Verify with 'hermes hooks list'."
}

_ts_install_claude() {
  _ts_need_cmd curl
  _ts_need_cmd python3
  local snippet="${HOME}/.config/teamshared/claude-mcp.json"
  mkdir -p "$(dirname "${snippet}")"
  _ts_fetch "${snippet}" "${ASSETS}/claude/mcp.json"
  _ts_apply_token "${snippet}"

  case "$(uname -s)" in
    Darwin)
      local config="${HOME}/Library/Application Support/Claude/claude_desktop_config.json"
      ;;
    *)
      local config="${HOME}/.config/Claude/claude_desktop_config.json"
      ;;
  esac

  mkdir -p "$(dirname "${config}")"
  _ts_merge_json_mcp "${snippet}" "${config}"
  echo "  MCP config → ${config}"
  echo "  snippet → ${snippet}"
}

_ts_install_openclaw() {
  _ts_need_cmd curl
  local cmds="${HOME}/.config/teamshared/openclaw-teamshared.sh"
  mkdir -p "$(dirname "${cmds}")"
  cat >"${cmds}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
openclaw config set 'mcp_servers.teamshared.url' '${TEAMSHARED_MCP_URL}'
openclaw config set 'mcp_servers.teamshared.headers.Authorization' "Bearer ${TEAMSHARED_TOKEN}"
openclaw config set 'mcp_servers.teamshared.timeout' 30
openclaw daemon restart
openclaw mcp list
EOF
  chmod +x "${cmds}"

  if command -v openclaw >/dev/null 2>&1; then
    bash "${cmds}"
  else
    echo "openclaw not on PATH. After installing OpenClaw, run:"
    echo "  bash ${cmds}"
  fi
}

_ts_need_cmd curl
_ts_choose_harness
_ts_prompt_token

case "${HARNESS}" in
  cursor) _ts_install_cursor ;;
  codex) _ts_install_codex ;;
  hermes) _ts_install_hermes ;;
  claude) _ts_install_claude ;;
  openclaw) _ts_install_openclaw ;;
  *) _ts_die "unknown harness: ${HARNESS}" ;;
esac

_ts_finish
"""


def unified_install_script(*, base_url: str) -> str:
    base = base_url.rstrip("/")
    mcp_url = f"{base}/mcp"
    return _INSTALL_SH.replace("__BASE__", base).replace("__MCP_URL__", mcp_url)


def install_index_html(*, base_url: str) -> str:
    base = base_url.rstrip("/")
    harnesses = ", ".join(sorted(KNOWN_AGENT_TYPES))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>teamshared install</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    code {{ background: #f4f4f5; padding: 0.125rem 0.375rem; border-radius: 0.25rem; }}
    pre {{ background: #f4f4f5; padding: 0.75rem; overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>Install teamshared</h1>
  <p>One script for every harness ({harnesses}). Downloads plugin files and MCP
  config from this server — no local clone of the repo required.</p>
  <pre>curl -fsSL {base}/install.sh | bash</pre>
  <p>The script prompts for your bearer token from <a href="/get-token">/get-token</a>
  and writes it into the harness MCP config.</p>
</body>
</html>"""
