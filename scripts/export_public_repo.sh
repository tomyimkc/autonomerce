#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
PREFIX="projects/autonomerce"
BRANCH="${1:-release/autonomerce-public}"

cd "$ROOT"

if [[ -n "$(git status --porcelain -- "$PREFIX")" ]]; then
  echo "BLOCKED: $PREFIX has uncommitted changes. Commit intentionally before export."
  exit 2
fi

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "BLOCKED: local branch already exists: $BRANCH"
  exit 2
fi

git subtree split --prefix="$PREFIX" -b "$BRANCH"
echo "Created subtree branch: $BRANCH"
echo "Review it before pushing to a new public repository."
