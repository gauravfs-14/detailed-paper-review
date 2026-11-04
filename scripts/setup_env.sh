#!/usr/bin/env bash
# Creates (once) a private Python env with the few packages the review scripts need.
# Usage: source <(bash scripts/setup_env.sh)   or just run it and use the printed PY path.
set -euo pipefail
VENV="${DPR_VENV:-$HOME/.cache/detailed-paper-review/venv}"
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv -q "$VENV" >&2
    VIRTUAL_ENV="$VENV" uv pip install -q pymupdf python-docx >&2
  else
    python3 -m venv "$VENV" >&2
    "$VENV/bin/pip" install -q pymupdf python-docx >&2
  fi
fi
"$VENV/bin/python" -c "import pymupdf, docx" >&2 || {
  echo "Package check failed; try: rm -rf '$VENV' and rerun" >&2; exit 1; }
echo "export PY='$VENV/bin/python'"
