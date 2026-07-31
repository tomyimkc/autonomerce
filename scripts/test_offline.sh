#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/apps/api:$ROOT/packages/offerrail:$ROOT"
python3 -m pytest -q tests
