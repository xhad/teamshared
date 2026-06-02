#!/usr/bin/env bash
# Start host Ollama bound on all interfaces so compose can reach it via
# host.docker.internal. Idempotent: exits 0 if something already answers :11434.
set -euo pipefail

export OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}"

if curl -fsS --max-time 2 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  echo "Ollama already listening on port 11434 (OLLAMA_HOST=${OLLAMA_HOST} if you need 0.0.0.0, restart it)."
  exit 0
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama CLI not on PATH; install from https://ollama.com or open the Ollama app." >&2
  exit 1
fi

# Menubar app may own the port; quit it first if serve fails to bind.
nohup ollama serve >>/tmp/teamshared-ollama-serve.log 2>&1 &
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    echo "Ollama serve started (OLLAMA_HOST=${OLLAMA_HOST}, log: /tmp/teamshared-ollama-serve.log)"
    exit 0
  fi
  sleep 1
done

echo "Ollama did not become ready on :11434; see /tmp/teamshared-ollama-serve.log" >&2
exit 1
