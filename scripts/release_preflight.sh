#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

readonly PYTHONPATH_VALUE="$ROOT/apps/api:$ROOT/packages/offerrail:$ROOT"
TMP_DIR=""

cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf -- "$TMP_DIR"
  fi
}
trap cleanup EXIT

step() {
  printf '\n==> %s\n' "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$1" >&2
    exit 2
  fi
}

for command_name in bash cmp env find mkdir mktemp npm python3 rm sort uv; do
  require_command "$command_name"
done

for required_path in \
  pyproject.toml \
  uv.lock \
  apps/web/package.json \
  apps/web/package-lock.json \
  examples/run_offline_demo.py \
  scripts/scan_public_secrets.py; do
  if [[ ! -f "$required_path" ]]; then
    printf 'ERROR: required release input is missing: %s\n' "$required_path" >&2
    exit 2
  fi
done

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/autonomerce-release-preflight.XXXXXX")"
mkdir -p "$TMP_DIR/home"
export UV_PROJECT_ENVIRONMENT="$TMP_DIR/venv"

step "Secret scan"
secret_scan_root="$TMP_DIR/secret-scan"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT" "$secret_scan_root" <<'PY'
from __future__ import annotations

from pathlib import Path
import shutil
import sys


source = Path(sys.argv[1])
destination = Path(sys.argv[2])
excluded_directories = {
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def ignore_generated(_directory: str, names: list[str]) -> list[str]:
    return sorted(excluded_directories.intersection(names))


shutil.copytree(source, destination, ignore=ignore_generated)
PY
PYTHONDONTWRITEBYTECODE=1 \
  python3 "$secret_scan_root/scripts/scan_public_secrets.py"

step "Shell syntax"
shell_count=0
while IFS= read -r shell_script; do
  bash -n "$shell_script"
  shell_count=$((shell_count + 1))
done < <(
  find . \
    -type d \( \
      -name .git -o \
      -name .next -o \
      -name .venv -o \
      -name __pycache__ -o \
      -name node_modules \
    \) -prune -o \
    -type f -name '*.sh' -print |
    LC_ALL=C sort
)
printf 'Validated %d shell script(s).\n' "$shell_count"

step "uv lock check"
uv lock --check

step "Python dependency sync"
uv sync --frozen --extra api --extra gemini --extra test

step "Python tests"
PYTHONPATH="$PYTHONPATH_VALUE" \
  uv run --frozen --no-sync python -m pytest -q tests

step "Offline demo repeatability"
demo_first="$TMP_DIR/offline-demo-first.json"
demo_second="$TMP_DIR/offline-demo-second.json"
venv_python="$(
  uv run --frozen --no-sync python -c \
    'import sys; print(sys.executable)'
)"

run_offline_demo() {
  local output_path="$1"
  env -i \
    HOME="$TMP_DIR/home" \
    LC_ALL=C \
    PATH="$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONPATH="$PYTHONPATH_VALUE" \
    PYTHONUTF8=1 \
    TZ=UTC \
    "$venv_python" examples/run_offline_demo.py --compact >"$output_path"
}

run_offline_demo "$demo_first"
run_offline_demo "$demo_second"

if ! cmp -s "$demo_first" "$demo_second"; then
  printf 'ERROR: offline demo output changed between identical runs.\n' >&2
  exit 1
fi

"$venv_python" - "$demo_first" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


path = Path(sys.argv[1])
raw = path.read_bytes()
payload = json.loads(raw)
diagnostics = payload["diagnostics"]

expected = {
    "credentialsUsed": False,
    "networkCalls": 0,
    "offline": True,
    "realFundsMoved": False,
}
actual = {key: diagnostics.get(key) for key in expected}
if actual != expected:
    raise SystemExit(
        f"offline demo diagnostics mismatch: expected {expected!r}, got {actual!r}"
    )

print(f"Offline demo output is byte-identical (sha256={hashlib.sha256(raw).hexdigest()}).")
PY

step "Web clean install, checks, tests, and build"
npm --prefix apps/web ci
npm --prefix apps/web run check

printf '\nRelease preflight: PASS\n'
