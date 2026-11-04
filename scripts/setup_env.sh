#!/usr/bin/env bash
# Creates (once) a private Python env with the few packages the review scripts need.
# Usage: source <(bash scripts/setup_env.sh)   or just run it and use the printed PY path.
set -euo pipefail
VENV="${DPR_VENV:-$HOME/.cache/detailed-paper-review/venv}"
if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p "$(dirname "$VENV")" 2>/dev/null && [ -w "$(dirname "$VENV")" ] || {
    echo "Cannot create $VENV (no write access; often the agent's sandbox)." >&2
    echo "Run this script once with write and network access (Codex: approve running it outside the sandbox;" >&2
    echo "Claude Code: allow it), or set DPR_VENV to a writable folder." >&2; exit 3; }
  if command -v uv >/dev/null 2>&1; then
    uv venv -q "$VENV" >&2
    VIRTUAL_ENV="$VENV" uv pip install -q pymupdf python-docx >&2 || {
      echo "Package install failed: network access is needed the first time." >&2; rm -rf "$VENV"; exit 3; }
  else
    python3 -m venv "$VENV" >&2
    "$VENV/bin/pip" install -q pymupdf python-docx >&2 || {
      echo "pip install failed: network access is needed the first time (see above)." >&2; rm -rf "$VENV"; exit 3; }
  fi
fi
"$VENV/bin/python" -c "import pymupdf, docx" >&2 || {
  echo "Package check failed; try: rm -rf '$VENV' and rerun" >&2; exit 1; }
echo "export PY='$VENV/bin/python'"
