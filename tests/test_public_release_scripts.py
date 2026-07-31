from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


PROJECT_PREFIX = Path("projects/autonomerce")
PUBLISH_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "publish_public_repo.sh"
)


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _init_repository(repository: Path) -> None:
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "Autonomerce Release Test")
    _git(repository, "config", "user.email", "release-test@example.invalid")


def _commit_all(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", message)
    return _git(repository, "rev-parse", "HEAD").stdout.strip()


def _install_publisher(repository: Path) -> Path:
    destination = repository / PROJECT_PREFIX / "scripts" / PUBLISH_SCRIPT.name
    destination.parent.mkdir(parents=True)
    shutil.copy2(PUBLISH_SCRIPT, destination)
    return destination


def _record_shallow_boundary(repository: Path, commit_id: str) -> Path:
    shallow_path = Path(
        _git(repository, "rev-parse", "--git-path", "shallow").stdout.strip()
    )
    if not shallow_path.is_absolute():
        shallow_path = repository / shallow_path
    shallow_path.write_text(f"{commit_id}\n", encoding="utf-8")
    assert (
        _git(repository, "rev-parse", "--is-shallow-repository").stdout.strip()
        == "true"
    )
    return shallow_path


def _publisher_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh_log = tmp_path / "gh.log"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$GH_LOG"\n'
        "exit 1\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["GH_LOG"] = str(gh_log)
    return environment, gh_log


def _run_publisher(
    repository: Path,
    publisher: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(publisher),
            "--owner",
            "test-owner",
            "--repo",
            "autonomerce-test",
            "--visibility",
            "public",
        ],
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_path_limited_boundary_markers_do_not_block_publication(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "source"
    _init_repository(repository)

    (repository / "root.txt").write_text("base\n", encoding="utf-8")
    actual_shallow_boundary = _commit_all(repository, "base without project")

    publisher = _install_publisher(repository)
    project_version = repository / PROJECT_PREFIX / "version.txt"
    project_version.write_text("one\n", encoding="utf-8")
    _commit_all(repository, "add project")

    (repository / "root.txt").write_text("unrelated\n", encoding="utf-8")
    path_limited_boundary = _commit_all(repository, "unrelated change")

    project_version.write_text("two\n", encoding="utf-8")
    _commit_all(repository, "update project")
    shallow_path = _record_shallow_boundary(
        repository,
        actual_shallow_boundary,
    )

    boundary_markers = {
        line.removeprefix("-")
        for line in _git(
            repository,
            "rev-list",
            "--boundary",
            "HEAD",
            "--",
            str(PROJECT_PREFIX),
        ).stdout.splitlines()
        if line.startswith("-")
    }
    assert path_limited_boundary in boundary_markers
    assert (
        _git(
            repository,
            "cat-file",
            "-e",
            f"{path_limited_boundary}:{PROJECT_PREFIX}",
            check=False,
        ).returncode
        == 0
    )
    assert shallow_path.read_text(encoding="utf-8").splitlines() == [
        actual_shallow_boundary
    ]

    environment, gh_log = _publisher_environment(tmp_path)
    completed = _run_publisher(repository, publisher, environment)

    assert completed.returncode == 2
    assert "shallow boundary" not in completed.stderr
    assert "GitHub CLI is not authenticated" in completed.stderr
    assert gh_log.read_text(encoding="utf-8").splitlines() == [
        "auth status --hostname github.com"
    ]


def test_actual_shallow_boundary_containing_project_blocks_publication(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "source"
    _init_repository(repository)

    publisher = _install_publisher(repository)
    (repository / PROJECT_PREFIX / "version.txt").write_text(
        "one\n",
        encoding="utf-8",
    )
    actual_shallow_boundary = _commit_all(repository, "add project")

    (repository / "root.txt").write_text("later\n", encoding="utf-8")
    _commit_all(repository, "later unrelated change")
    _record_shallow_boundary(repository, actual_shallow_boundary)

    environment, gh_log = _publisher_environment(tmp_path)
    completed = _run_publisher(repository, publisher, environment)

    assert completed.returncode == 2
    assert (
        f"the shallow boundary {actual_shallow_boundary} contains "
        f"{PROJECT_PREFIX}"
    ) in completed.stderr
    assert "fetch the missing project history before publication" in completed.stderr
    assert not gh_log.exists()
