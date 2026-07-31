#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
VENV="${VIRTUAL_ENV:-$ROOT/.venv}"

if [ -x "$VENV/bin/python" ] && [ -x "$VENV/bin/uvicorn" ]; then
  PYTHON="$VENV/bin/python"
  UVICORN="$VENV/bin/uvicorn"
else
  PYTHON="${PYTHON:-python3}"
  UVICORN="${UVICORN:-uvicorn}"
fi

cd "$ROOT"
"$PYTHON" infra/runtime_preflight.py

exec "$UVICORN" autonomerce.api.app:create_app \
  --factory \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --workers 1
