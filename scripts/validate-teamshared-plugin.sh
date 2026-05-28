#!/usr/bin/env bash
# Quick structural checks for plugins/teamshared before marketplace submission.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN="$ROOT/plugins/teamshared"
FAIL=0

check() {
  if [[ -e "$1" ]]; then
    echo "ok  $1"
  else
    echo "MISSING  $1"
    FAIL=1
  fi
}

echo "Validating teamshared plugin at $PLUGIN"
check "$PLUGIN/.cursor-plugin/plugin.json"
check "$ROOT/.cursor-plugin/marketplace.json"
check "$PLUGIN/mcp.json"
check "$PLUGIN/rules/teamshared.mdc"
check "$PLUGIN/skills/teamshared/SKILL.md"
check "$PLUGIN/skills/continual-learning/SKILL.md"
check "$PLUGIN/agents/agents-memory-updater.md"
check "$PLUGIN/hooks/hooks.json"
check "$PLUGIN/hooks/continual-learning-stop.ts"
check "$PLUGIN/hooks/teamshared-state.ts"
check "$PLUGIN/assets/logo.svg"
check "$PLUGIN/LICENSE"
check "$PLUGIN/README.md"
check "$PLUGIN/CHANGELOG.md"

if command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY' "$PLUGIN/.cursor-plugin/plugin.json" "$ROOT/.cursor-plugin/marketplace.json"
import json, sys
for path in sys.argv[1:]:
    with open(path) as f:
        json.load(f)
    print(f"ok  JSON  {path}")
PY
else
  echo "skip JSON parse (python3 not found)"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "Validation failed."
  exit 1
fi

echo "All checks passed."
