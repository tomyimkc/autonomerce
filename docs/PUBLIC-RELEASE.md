<!-- AUTONOMERCE_PUBLIC_EXPORT_V1 -->

# Public repository release

This document defines the safe boundary for exporting
`projects/autonomerce` from the private Sophia monorepo into a standalone
GitHub repository.

The publication helper is intentionally conservative:

- its default mode is a read-only dry run;
- publishing requires explicit `--owner`, `--repo`, `--visibility`, and
  `--publish` arguments;
- it refuses any uncommitted change under `projects/autonomerce`;
- it validates the exact subtree commit in an isolated temporary clone;
- it will not force-push, delete, change an existing repository's visibility,
  or replace an unrecognized non-empty repository.

Passing this automation is a source-integrity check. It is **not** proof of
production readiness, contest eligibility, legal approval, customer consent,
live payment success, or security certification.

## Prerequisites

Run the helper from the Sophia monorepo with the complete history of
`projects/autonomerce`. A shallow monorepo is accepted only when the project is
absent at every shallow boundary, proving that the available history includes
the project's introduction. The following commands must already be available:

- `git`, including `git subtree`;
- `gh`;
- `python3` with the project's test dependencies;
- `tar`.

The canonical `scripts/release_preflight.sh` also requires `uv`, `npm`, and
their dependency registries to be reachable when the required packages are not
already cached.

The repository owner must authenticate GitHub CLI and the configured Git
transport before running the helper:

```bash
gh auth login
gh auth status
```

Authentication is deliberately outside the script. The helper has no token,
password, key, credential-file, login, logout, refresh, or secret-storage
option. Do not paste credentials into command arguments, source files, issue
comments, logs, or chat.

## Safe dry run

With no arguments, the helper uses the authenticated GitHub login as the owner,
`autonomerce` as the repository name, and `public` as the requested visibility:

```bash
./projects/autonomerce/scripts/publish_public_repo.sh
```

Inputs can be previewed without enabling publication:

```bash
./projects/autonomerce/scripts/publish_public_repo.sh \
  --owner OWNER \
  --repo autonomerce \
  --visibility public
```

The dry run:

1. refuses a dirty `projects/autonomerce` tree;
2. creates a disposable local clone without adding a source-repository ref;
3. runs `git subtree split` only inside that disposable clone;
4. checks required release files and rejects tracked credentials, generated
   caches, databases, logs, symlinks, and gitlinks;
5. runs the canonical `scripts/release_preflight.sh` inside the disposable
   export, including its secret scan, shell syntax checks, frozen dependency
   checks, Python tests, repeatable offline demo, and clean web install/check;
6. keeps dependency environments, build output, bytecode, and test caches out
   of the source worktree;
7. inspects the target repository through authenticated, read-only GitHub API
   calls.

Temporary files are removed on exit. The dry run does not create a GitHub
repository, create or update a source-repository branch, or push a remote ref.

## Explicit publication

After reviewing the dry-run output, the owner may opt in to repository creation
and a normal non-force push:

```bash
./projects/autonomerce/scripts/publish_public_repo.sh \
  --owner OWNER \
  --repo autonomerce \
  --visibility public \
  --publish
```

All three target arguments are mandatory with `--publish`; defaults are not
accepted for a mutating run. The helper pushes the subtree commit to `main`.

The operation is idempotent for the same committed source state:

- if the target does not exist, the helper creates it and pushes;
- if creation succeeded but the push failed, rerunning can complete the push to
  the empty repository;
- if the recognized public export already contains the commit, a normal push
  reports that it is up to date;
- if a recognized export has an older compatible subtree history, the normal
  push advances it;
- if histories diverge, the non-force push fails rather than rewriting the
  public repository.

The helper never uses `--force`, `--force-with-lease`, repository deletion, or
visibility mutation.

## Existing-repository safety

An existing empty repository is eligible for the first push only when its
visibility matches `--visibility`.

An existing non-empty repository must satisfy all of these checks:

1. its default branch is `main`;
2. its visibility matches the requested visibility;
3. `docs/PUBLIC-RELEASE.md` contains the stable
   `AUTONOMERCE_PUBLIC_EXPORT_V1` marker;
4. `pyproject.toml` identifies the project as `autonomerce`;
5. `PREEXISTING-ASSET-DISCLOSURE.md` exists.

If those checks fail, publication stops before any push. Do not weaken the
checks to reuse an unrelated repository. The owner should choose a new
repository name or manually resolve the repository's purpose and contents.

These markers recognize the expected export; they do not make a force update
safe. Git still enforces the final fast-forward check.

## Owner-only boundaries

Automation may perform source checks, inspect repository state, create the
explicitly named repository, and make a non-force `main` push. The human or
organization owner remains responsible for:

- choosing and approving the GitHub owner, repository name, and visibility;
- establishing account authentication, organization authorization, and Git
  transport access;
- confirming contest dates, eligibility, ownership, licensing, notices, and
  the pre-existing asset disclosure;
- confirming that no customer identity, prompt, artifact, quote, transaction,
  consent record, or private evidence is published without the required
  permission;
- reviewing repository settings, access, branch protection, security features,
  topics, description, and public-facing links;
- deciding whether and when a private/internal repository becomes public;
- running and reviewing any credentialed Gemini, Circle, deployment, or payment
  checks;
- creating a release or tag and ensuring its commit matches the submitted
  Devpost/deployment revision;
- rotating and remediating any secret found before publication.

The helper cannot make those decisions and must not be treated as owner
approval.

## Full release review

The publication preflight is deliberately credential-free and does not replace
the full release checklist. Before launch, also review:

- `README.md`;
- `PROJECT-CONTRACT.md`;
- `PREEXISTING-ASSET-DISCLOSURE.md`;
- `security/THREAT-MODEL.md`;
- `docs/submission/JUDGE-CHECKLIST.md`;
- `docs/submission/SETUP-PROOF-CHECKLIST.md`;
- `docs/submission/KNOWN-LIMITATIONS.md`.

The canonical release preflight can also be rerun directly from
`projects/autonomerce`:

```bash
./scripts/release_preflight.sh
```

When working inside Sophia, run the repository claim guard from the monorepo
root:

```bash
python3 tools/lint_claims.py
```

Credentialed or live service preflights remain separate owner-controlled
operations. A successful source publication does not assert that those checks
were run or passed.

## Recovery

- **Dirty project tree:** inspect `git status --short -- projects/autonomerce`;
  preserve other agents' work and commit only the intended project changes.
- **Authentication failure:** the owner runs `gh auth status` and repairs the
  authenticated session outside this script.
- **Non-empty unrelated repository:** stop; use a new name or resolve it
  manually. Never add the marker merely to bypass the guard.
- **Visibility mismatch:** stop; the owner decides whether to change visibility
  manually or rerun with the repository's actual visibility.
- **Non-fast-forward push:** stop and review both histories. The helper will not
  rewrite the remote.
- **Repository created but push failed:** the empty repository is safe to
  inspect; rerun the same explicit publish command after Git transport access is
  repaired.
