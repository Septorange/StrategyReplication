#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${STRATEGY_LAB_PYTHON:-/opt/anaconda3/bin/python}"
PORT="${PORT:-${STRATEGY_LAB_PORT:-8003}}"
if [[ "${1:-}" == "--port" && -n "${2:-}" ]]; then
  PORT="$2"
  shift 2
fi
if [[ $# -gt 0 ]] || ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo "Usage: PORT=8003 ./run_local.sh  or  ./run_local.sh --port 8003" >&2
  exit 2
fi
if command -v lsof >/dev/null 2>&1; then
  EXISTING="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$EXISTING" ]]; then
    echo "ERROR: Port $PORT is occupied. Choose PORT or --port explicitly." >&2
    echo "$EXISTING" >&2
    exit 3
  fi
fi
if [[ ! -f "$ROOT/data/v6_web/manifest.json" ]]; then
  echo "ERROR: Frozen V6 web snapshot is missing; see README.md." >&2
  exit 4
fi
cd "$ROOT"
echo "Strategy Lab V0.6 · Research Analytics"
echo "Project: $ROOT"
echo "Local URL: http://127.0.0.1:$PORT"
exec "$PY" -m uvicorn backend.app:app --host 127.0.0.1 --port "$PORT"
