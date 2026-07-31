#!/usr/bin/env bash
set -euo pipefail

readonly PREFIX="projects/autonomerce"
readonly DEFAULT_REPO="autonomerce"
readonly DEFAULT_VISIBILITY="public"
readonly TARGET_BRANCH="main"
readonly RELEASE_MARKER="AUTONOMERCE_PUBLIC_EXPORT_V1"
readonly EXIT_BLOCKED=2

PUBLISH=0
OWNER=""
OWNER_WAS_SET=0
REPO_NAME="$DEFAULT_REPO"
REPO_WAS_SET=0
VISIBILITY="$DEFAULT_VISIBILITY"
VISIBILITY_WAS_SET=0
TEMP_ROOT=""

usage() {
  cat <<'EOF'
Usage:
  publish_public_repo.sh [--owner OWNER] [--repo NAME]
                         [--visibility public|private|internal] [--dry-run]
  publish_public_repo.sh --owner OWNER --repo NAME
                         --visibility public|private|internal --publish

Default behavior is a read-only dry run. It validates the committed Autonomerce
subtree in an isolated temporary clone and inspects the target GitHub repository,
but it does not create a repository, update a ref, or push.

Publishing requires all target values to be explicit plus --publish. The script:
  - refuses an uncommitted projects/autonomerce tree;
  - requires an existing authenticated GitHub CLI session;
  - runs the public secret scan and release preflight on the exact subtree split;
  - creates only a missing repository, or updates an empty/recognized export;
  - uses a normal non-force push to main.

The script never accepts, reads, prints, stores, or refreshes credentials. The
repository owner must establish GitHub CLI and Git transport authentication
outside this script.
EOF
}

log() {
  printf '%s\n' "$*"
}

blocked() {
  printf 'BLOCKED: %s\n' "$*" >&2
  exit "$EXIT_BLOCKED"
}

cleanup() {
  if [[ -n "$TEMP_ROOT" && -d "$TEMP_ROOT" ]]; then
    rm -rf -- "$TEMP_ROOT"
  fi
}
trap cleanup EXIT HUP INT TERM

require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    blocked "required command is unavailable: $1"
}

require_value() {
  local option="$1"
  local value="${2:-}"
  [[ -n "$value" && "$value" != --* ]] ||
    blocked "$option requires a value"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner)
      require_value "$1" "${2:-}"
      OWNER="$2"
      OWNER_WAS_SET=1
      shift 2
      ;;
    --owner=*)
      OWNER="${1#*=}"
      [[ -n "$OWNER" ]] || blocked "--owner requires a value"
      OWNER_WAS_SET=1
      shift
      ;;
    --repo)
      require_value "$1" "${2:-}"
      REPO_NAME="$2"
      REPO_WAS_SET=1
      shift 2
      ;;
    --repo=*)
      REPO_NAME="${1#*=}"
      [[ -n "$REPO_NAME" ]] || blocked "--repo requires a value"
      REPO_WAS_SET=1
      shift
      ;;
    --visibility)
      require_value "$1" "${2:-}"
      VISIBILITY="$2"
      VISIBILITY_WAS_SET=1
      shift 2
      ;;
    --visibility=*)
      VISIBILITY="${1#*=}"
      [[ -n "$VISIBILITY" ]] || blocked "--visibility requires a value"
      VISIBILITY_WAS_SET=1
      shift
      ;;
    --publish)
      PUBLISH=1
      shift
      ;;
    --dry-run)
      PUBLISH=0
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      blocked "unknown argument: $1"
      ;;
  esac
done

for command_name in \
  awk \
  cat \
  gh \
  git \
  grep \
  mkdir \
  mktemp \
  python3 \
  rm \
  sed \
  tar; do
  require_command "$command_name"
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)" ||
  blocked "run this script from a git worktree containing $PREFIX"
cd "$ROOT"

[[ -d "$ROOT/$PREFIX" ]] ||
  blocked "expected project directory is missing: $PREFIX"
git cat-file -e "HEAD:$PREFIX" 2>/dev/null ||
  blocked "$PREFIX is not present in HEAD"

PROJECT_STATUS="$(
  GIT_OPTIONAL_LOCKS=0 \
    git status --porcelain --untracked-files=all -- "$PREFIX"
)"
if [[ -n "$PROJECT_STATUS" ]]; then
  printf '%s\n' "$PROJECT_STATUS" >&2
  blocked "$PREFIX has uncommitted changes; commit them intentionally before publication"
fi

if [[ "$(git rev-parse --is-shallow-repository)" == "true" ]]; then
  TRUNCATED_PROJECT_BOUNDARY=""
  while IFS= read -r boundary_commit; do
    if git cat-file -e "$boundary_commit:$PREFIX" 2>/dev/null; then
      TRUNCATED_PROJECT_BOUNDARY="$boundary_commit"
      break
    fi
  done < <(
    git rev-list --boundary HEAD -- "$PREFIX" |
      sed -n 's/^-//p'
  )
  [[ -z "$TRUNCATED_PROJECT_BOUNDARY" ]] ||
    blocked "the shallow boundary $TRUNCATED_PROJECT_BOUNDARY contains $PREFIX; fetch the missing project history before publication"
fi

case "$VISIBILITY" in
  public | private | internal) ;;
  *) blocked "visibility must be public, private, or internal" ;;
esac

[[ "$REPO_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$ ]] ||
  blocked "invalid GitHub repository name: $REPO_NAME"
[[ "$REPO_NAME" != "." && "$REPO_NAME" != ".." ]] ||
  blocked "invalid GitHub repository name: $REPO_NAME"

gh auth status --hostname github.com >/dev/null 2>&1 ||
  blocked "GitHub CLI is not authenticated; the owner must run 'gh auth login' separately"

if [[ -z "$OWNER" ]]; then
  OWNER="$(gh api user --jq .login 2>/dev/null)" ||
    blocked "could not determine the authenticated GitHub owner"
fi
[[ "$OWNER" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] ||
  blocked "invalid GitHub owner: $OWNER"

if [[ "$PUBLISH" -eq 1 ]]; then
  if [[ "$OWNER_WAS_SET" -ne 1 || "$REPO_WAS_SET" -ne 1 ||
        "$VISIBILITY_WAS_SET" -ne 1 ]]; then
    blocked "--publish requires explicit --owner, --repo, and --visibility values"
  fi
fi

SOURCE_HEAD="$(git rev-parse HEAD)"
TARGET="$OWNER/$REPO_NAME"
MODE="dry-run"
[[ "$PUBLISH" -eq 1 ]] && MODE="publish"

log "Mode:       $MODE"
log "Source:     $SOURCE_HEAD ($PREFIX)"
log "Target:     $TARGET"
log "Visibility: $VISIBILITY"
log "Branch:     $TARGET_BRANCH"

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/autonomerce-public.XXXXXX")" ||
  blocked "could not create an isolated temporary directory"
SPLIT_REPO="$TEMP_ROOT/source"
EXPORT_ROOT="$TEMP_ROOT/export"
mkdir -p "$EXPORT_ROOT"

log "Preparing an isolated subtree split..."
git clone --quiet --no-checkout --local "$ROOT" "$SPLIT_REPO" ||
  blocked "could not create the isolated local clone"

SPLIT_SHA="$(
  git -C "$SPLIT_REPO" subtree split --prefix="$PREFIX" "$SOURCE_HEAD"
)" || blocked "git subtree split failed"
[[ "$SPLIT_SHA" =~ ^[0-9a-f]{40,64}$ ]] ||
  blocked "git subtree split returned an invalid commit id"
git -C "$SPLIT_REPO" cat-file -e "$SPLIT_SHA^{commit}" 2>/dev/null ||
  blocked "the subtree split commit is unavailable"

git -C "$SPLIT_REPO" archive "$SPLIT_SHA" | tar -x -C "$EXPORT_ROOT" ||
  blocked "could not materialize the subtree export for preflight"

log "Subtree:    $SPLIT_SHA"
log "Running release preflight on the exact exported commit..."

REQUIRED_FILES=(
  "README.md"
  "LICENSE"
  "NOTICE"
  "PROJECT-CONTRACT.md"
  "PREEXISTING-ASSET-DISCLOSURE.md"
  "pyproject.toml"
  "uv.lock"
  "scripts/scan_public_secrets.py"
  "scripts/release_preflight.sh"
  "scripts/test_offline.sh"
  "scripts/publish_public_repo.sh"
  "docs/PUBLIC-RELEASE.md"
)
for required_file in "${REQUIRED_FILES[@]}"; do
  [[ -f "$EXPORT_ROOT/$required_file" ]] ||
    blocked "required public-release file is missing: $required_file"
done

grep -Fq "$RELEASE_MARKER" "$EXPORT_ROOT/docs/PUBLIC-RELEASE.md" ||
  blocked "public release marker is missing from docs/PUBLIC-RELEASE.md"
grep -Eq '^name[[:space:]]*=[[:space:]]*"autonomerce"[[:space:]]*$' \
  "$EXPORT_ROOT/pyproject.toml" ||
  blocked "pyproject.toml does not identify the Autonomerce project"

FORBIDDEN_PATH=""
while IFS= read -r -d '' tracked_path; do
  case "$tracked_path" in
    .env | .env.* | */.env | */.env.*)
      if [[ "$tracked_path" != ".env.example" &&
            "$tracked_path" != */.env.example ]]; then
        FORBIDDEN_PATH="$tracked_path"
        break
      fi
      ;;
    .venv/* | */.venv/* | node_modules/* | */node_modules/* | \
      .next/* | */.next/* | __pycache__/* | */__pycache__/* | \
      .pytest_cache/* | */.pytest_cache/* | evidence/private/* | \
      */evidence/private/* | *.pem | *.key | *.p12 | *.pfx | *.jks | \
      *.keystore | *.sqlite | *.sqlite3 | *.db | *.log)
      FORBIDDEN_PATH="$tracked_path"
      break
      ;;
  esac
done < <(git -C "$SPLIT_REPO" ls-tree -r -z --name-only "$SPLIT_SHA")
[[ -z "$FORBIDDEN_PATH" ]] ||
  blocked "forbidden generated, private, or credential-like path is tracked: $FORBIDDEN_PATH"

UNSAFE_TREE_ENTRY="$(
  git -C "$SPLIT_REPO" ls-tree -r "$SPLIT_SHA" |
    awk '$1 == "120000" || $2 == "commit" { print }'
)"
[[ -z "$UNSAFE_TREE_ENTRY" ]] ||
  blocked "symlinks and gitlinks are not allowed in the public export: $UNSAFE_TREE_ENTRY"

(
  cd "$EXPORT_ROOT"
  export CI="${CI:-true}"
  export UV_NO_PROGRESS="${UV_NO_PROGRESS:-true}"
  bash scripts/release_preflight.sh
)

log "RELEASE PREFLIGHT: PASS"

REPO_EXISTS=0
REPO_ERROR="$TEMP_ROOT/repo-error"
if gh api "repos/$TARGET" --silent 2>"$REPO_ERROR"; then
  REPO_EXISTS=1
elif grep -Eq 'HTTP 404|Not Found' "$REPO_ERROR"; then
  REPO_EXISTS=0
else
  cat "$REPO_ERROR" >&2
  blocked "could not safely determine whether $TARGET exists"
fi

REMOTE_URL=""
REMOTE_SSH_URL=""
if [[ "$REPO_EXISTS" -eq 1 ]]; then
  REPO_JSON="$(
    gh repo view "$TARGET" \
      --json nameWithOwner,isEmpty,visibility,defaultBranchRef,url,sshUrl
  )" || blocked "could not inspect existing repository: $TARGET"

  REMOTE_EMPTY="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; print("true" if json.load(sys.stdin)["isEmpty"] else "false")'
  )"
  REMOTE_VISIBILITY="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["visibility"].lower())'
  )"
  REMOTE_DEFAULT_BRANCH="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("defaultBranchRef") or {}).get("name", ""))'
  )"
  REMOTE_URL="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])'
  )"
  REMOTE_SSH_URL="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["sshUrl"])'
  )"

  [[ "$REMOTE_VISIBILITY" == "$VISIBILITY" ]] ||
    blocked "$TARGET visibility is $REMOTE_VISIBILITY, not requested $VISIBILITY; change it manually or use the matching input"

  if [[ "$REMOTE_EMPTY" == "false" ]]; then
    [[ "$REMOTE_DEFAULT_BRANCH" == "$TARGET_BRANCH" ]] ||
      blocked "$TARGET uses default branch '$REMOTE_DEFAULT_BRANCH'; refusing to overwrite it"

    REMOTE_RELEASE_DOC="$(
      gh api -H "Accept: application/vnd.github.raw" \
        "repos/$TARGET/contents/docs/PUBLIC-RELEASE.md" 2>/dev/null
    )" || blocked "$TARGET is non-empty and lacks a verifiable Autonomerce release marker"
    grep -Fq "$RELEASE_MARKER" <<<"$REMOTE_RELEASE_DOC" ||
      blocked "$TARGET is non-empty and is not a recognized Autonomerce public export"

    REMOTE_PYPROJECT="$(
      gh api -H "Accept: application/vnd.github.raw" \
        "repos/$TARGET/contents/pyproject.toml" 2>/dev/null
    )" || blocked "$TARGET is non-empty and lacks the Autonomerce project manifest"
    grep -Eq '^name[[:space:]]*=[[:space:]]*"autonomerce"[[:space:]]*$' \
      <<<"$REMOTE_PYPROJECT" ||
      blocked "$TARGET is non-empty and has an unrelated project manifest"

    gh api "repos/$TARGET/contents/PREEXISTING-ASSET-DISCLOSURE.md" \
      --silent >/dev/null 2>&1 ||
      blocked "$TARGET is non-empty and lacks the required asset disclosure"

    log "Remote:     recognized non-empty Autonomerce export"
  else
    log "Remote:     existing empty repository"
  fi
else
  log "Remote:     repository does not exist"
fi

if [[ "$PUBLISH" -ne 1 ]]; then
  if [[ "$REPO_EXISTS" -eq 0 ]]; then
    log "DRY RUN: would create $TARGET with $VISIBILITY visibility, then push $SPLIT_SHA to $TARGET_BRANCH."
  else
    log "DRY RUN: would non-force push $SPLIT_SHA to $TARGET:$TARGET_BRANCH."
  fi
  log "DRY RUN: no repository, ref, or remote was changed."
  exit 0
fi

if [[ "$REPO_EXISTS" -eq 0 ]]; then
  log "Creating $VISIBILITY repository $TARGET..."
  gh repo create "$TARGET" "--$VISIBILITY" \
    --description "Autonomerce: bounded agentic commerce with deterministic payment controls" ||
    blocked "GitHub repository creation failed; no push was attempted"

  REPO_JSON="$(
    gh repo view "$TARGET" --json visibility,url,sshUrl
  )" || blocked "repository was created, but its state could not be verified"
  CREATED_VISIBILITY="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["visibility"].lower())'
  )"
  [[ "$CREATED_VISIBILITY" == "$VISIBILITY" ]] ||
    blocked "repository was created with unexpected visibility: $CREATED_VISIBILITY"
  REMOTE_URL="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])'
  )"
  REMOTE_SSH_URL="$(
    printf '%s' "$REPO_JSON" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["sshUrl"])'
  )"
fi

GIT_PROTOCOL="$(gh config get git_protocol --host github.com 2>/dev/null || true)"
PUSH_URL="$REMOTE_URL"
[[ "$GIT_PROTOCOL" == "ssh" ]] && PUSH_URL="$REMOTE_SSH_URL"
[[ -n "$PUSH_URL" ]] || blocked "could not determine the authenticated git transport URL"

log "Pushing with a normal non-force update..."
GIT_TERMINAL_PROMPT=0 \
  git -C "$SPLIT_REPO" push "$PUSH_URL" \
    "$SPLIT_SHA:refs/heads/$TARGET_BRANCH" ||
  blocked "push failed safely; no force push or remote rewrite was attempted"

REMOTE_SHA="$(
  gh api "repos/$TARGET/git/ref/heads/$TARGET_BRANCH" --jq .object.sha
)" || blocked "push completed, but the remote branch could not be verified"
[[ "$REMOTE_SHA" == "$SPLIT_SHA" ]] ||
  blocked "remote verification mismatch: expected $SPLIT_SHA, found $REMOTE_SHA"

log "PUBLISHED: $TARGET:$TARGET_BRANCH is exactly $SPLIT_SHA"
log "Owner action still required: review visibility, branch protection, release/tag, legal/contest eligibility, and public links."
