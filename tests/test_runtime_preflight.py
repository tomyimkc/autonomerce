from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "autonomerce_runtime_preflight",
    ROOT / "infra" / "runtime_preflight.py",
)
assert SPEC is not None and SPEC.loader is not None
runtime_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_preflight)


RUNTIME_ENV_NAMES = {
    "AUTONOMERCE_API_AUTH_MODE",
    "AUTONOMERCE_API_BEARER_TOKEN",
    "AUTONOMERCE_API_PRIVATE_ORIGIN",
    "AUTONOMERCE_DEPLOYMENT_MODE",
    "AUTONOMERCE_FULFILLMENT_ADAPTER_FACTORY",
    "AUTONOMERCE_GEMINI_MODEL",
    "AUTONOMERCE_MODE",
    "AUTONOMERCE_PAYMENT_ADAPTER_FACTORY",
    "AUTONOMERCE_PAYMENT_MODE",
    "AUTONOMERCE_PAYMENT_STORE_DURABILITY",
    "AUTONOMERCE_PRODUCTIZER_MODE",
    "AUTONOMERCE_SELLER_EXECUTOR_FACTORY",
    "AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY",
    "AUTONOMERCE_WEB_PUBLIC_ORIGIN",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "K_SERVICE",
} | runtime_preflight.LEGACY_PAYMENT_ENV


def _configure_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    deployment_mode: str,
    runtime_mode: str,
) -> None:
    for name in RUNTIME_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    values = {
        "AUTONOMERCE_API_AUTH_MODE": "service-to-service",
        "AUTONOMERCE_API_BEARER_TOKEN": "test-only-application-bearer",
        "AUTONOMERCE_API_PRIVATE_ORIGIN": (
            "https://autonomerce-api.example.run.app"
        ),
        "AUTONOMERCE_DEPLOYMENT_MODE": deployment_mode,
        "AUTONOMERCE_MODE": runtime_mode,
        "AUTONOMERCE_PAYMENT_MODE": "offline",
        "AUTONOMERCE_PAYMENT_STORE_DURABILITY": "memory-offline",
        "AUTONOMERCE_WEB_PUBLIC_ORIGIN": "https://app.example.com",
        "K_SERVICE": "autonomerce-api",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _enable_vertex_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTONOMERCE_GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "autonomerce-test")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")


def _factory_module(
    monkeypatch: pytest.MonkeyPatch,
    factory: object,
) -> str:
    module_name = "autonomerce_test_publication_factory"
    module = ModuleType(module_name)
    module.build_verifier = factory
    monkeypatch.setitem(sys.modules, module_name, module)
    return f"{module_name}:build_verifier"


def test_live_preflight_allows_explicitly_disabled_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AUTONOMERCE_RECEIPT_PUBLICATION_MODE",
        "disabled",
    )
    monkeypatch.delenv(
        "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY",
        raising=False,
    )

    runtime_preflight.validate_publication_configuration()


def test_live_preflight_requires_callable_verifier_for_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AUTONOMERCE_RECEIPT_PUBLICATION_MODE",
        "verified",
    )
    monkeypatch.delenv(
        "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY",
        raising=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        runtime_preflight.validate_publication_configuration()
    assert exc_info.value.code == runtime_preflight.EXIT_BLOCKED


def test_live_preflight_loads_verified_publication_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AUTONOMERCE_RECEIPT_PUBLICATION_MODE",
        "verified",
    )
    monkeypatch.setenv(
        "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY",
        _factory_module(monkeypatch, lambda: lambda **_: True),
    )

    runtime_preflight.validate_publication_configuration()


def test_live_preflight_rejects_non_callable_publication_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AUTONOMERCE_RECEIPT_PUBLICATION_MODE",
        "verified",
    )
    monkeypatch.setenv(
        "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY",
        _factory_module(monkeypatch, lambda: object()),
    )

    with pytest.raises(SystemExit) as exc_info:
        runtime_preflight.validate_publication_configuration()
    assert exc_info.value.code == runtime_preflight.EXIT_BLOCKED


def test_cloud_run_private_offline_mode_remains_gemini_independent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_runtime(
        monkeypatch,
        deployment_mode="cloud-run-private-offline",
        runtime_mode="offline",
    )

    assert runtime_preflight.main() == 0
    output = capsys.readouterr()
    assert "deployment=cloud-run-private-offline" in output.out
    assert "runtime=offline" in output.out
    assert "payment=offline" in output.out


def test_cloud_run_private_gemini_accepts_vertex_with_offline_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_runtime(
        monkeypatch,
        deployment_mode="cloud-run-private-gemini",
        runtime_mode="gemini",
    )
    _enable_vertex_gemini(monkeypatch)
    monkeypatch.setenv("AUTONOMERCE_PRODUCTIZER_MODE", "gemini")

    assert runtime_preflight.main() == 0
    output = capsys.readouterr()
    assert "deployment=cloud-run-private-gemini" in output.out
    assert "runtime=gemini" in output.out
    assert "payment=offline" in output.out


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AUTONOMERCE_GEMINI_MODEL", ""),
        ("GOOGLE_CLOUD_LOCATION", ""),
        ("GOOGLE_CLOUD_PROJECT", ""),
        ("GOOGLE_GENAI_USE_VERTEXAI", ""),
        ("GOOGLE_GENAI_USE_VERTEXAI", "false"),
    ],
)
def test_cloud_run_private_gemini_requires_explicit_vertex_configuration(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _configure_runtime(
        monkeypatch,
        deployment_mode="cloud-run-private-gemini",
        runtime_mode="gemini",
    )
    _enable_vertex_gemini(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit) as exc_info:
        runtime_preflight.main()
    assert exc_info.value.code == runtime_preflight.EXIT_BLOCKED


@pytest.mark.parametrize(
    "factory_name",
    sorted(runtime_preflight.GEMINI_OFFLINE_FORBIDDEN_FACTORIES),
)
def test_cloud_run_private_gemini_rejects_live_adapter_factories(
    monkeypatch: pytest.MonkeyPatch,
    factory_name: str,
) -> None:
    _configure_runtime(
        monkeypatch,
        deployment_mode="cloud-run-private-gemini",
        runtime_mode="gemini",
    )
    _enable_vertex_gemini(monkeypatch)
    monkeypatch.setenv(factory_name, "autonomerce.live:build")

    with pytest.raises(SystemExit) as exc_info:
        runtime_preflight.main()
    assert exc_info.value.code == runtime_preflight.EXIT_BLOCKED


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AUTONOMERCE_MODE", "offline"),
        ("AUTONOMERCE_PAYMENT_MODE", "testnet"),
        (
            "AUTONOMERCE_PAYMENT_STORE_DURABILITY",
            "single-host-persistent-volume",
        ),
        ("AUTONOMERCE_PRODUCTIZER_MODE", "offline"),
    ],
)
def test_cloud_run_private_gemini_rejects_boundary_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _configure_runtime(
        monkeypatch,
        deployment_mode="cloud-run-private-gemini",
        runtime_mode="gemini",
    )
    _enable_vertex_gemini(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit) as exc_info:
        runtime_preflight.main()
    assert exc_info.value.code == runtime_preflight.EXIT_BLOCKED


def _fake_gcloud(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gcloud-calls.jsonl"
    executable = bin_dir / "gcloud"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ["GCLOUD_LOG"]).open("a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
if args[:3] == ["run", "services", "get-iam-policy"]:
    print(json.dumps({
        "bindings": [{
            "role": "roles/run.invoker",
            "members": [os.environ["AUTONOMERCE_ALLOWED_INVOKER"]],
        }],
    }))
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return bin_dir, log_path


def _deploy_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir, log_path = _fake_gcloud(tmp_path)
    environment = {
        "AUTONOMERCE_ALLOWED_INVOKER": (
            "serviceAccount:trusted-caller@example.iam.gserviceaccount.com"
        ),
        "AUTONOMERCE_API_AUTH_MODE": "service-to-service",
        "AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF": "api-bearer:7",
        "AUTONOMERCE_API_IMAGE": (
            "us-central1-docker.pkg.dev/example/repo/autonomerce-api@sha256:"
            + ("a" * 64)
        ),
        "AUTONOMERCE_API_PRIVATE_ORIGIN": (
            "https://autonomerce-api.example.run.app"
        ),
        "AUTONOMERCE_RUNTIME_SERVICE_ACCOUNT": (
            "autonomerce-api@example.iam.gserviceaccount.com"
        ),
        "AUTONOMERCE_TRUSTED_HOSTS": (
            "autonomerce-api.example.run.app"
        ),
        "AUTONOMERCE_WEB_PUBLIC_ORIGIN": "https://app.example.com",
        "GCLOUD_LOG": str(log_path),
        "GOOGLE_CLOUD_PROJECT": "autonomerce-test",
        "GOOGLE_CLOUD_REGION": "us-central1",
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    return environment, log_path


def _run_deploy(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "infra" / "deploy_cloud_run_api.sh")],
        check=False,
        capture_output=True,
        cwd=ROOT,
        env=environment,
        text=True,
    )


def _gcloud_calls(log_path: Path) -> list[list[str]]:
    if not log_path.exists():
        return []
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]


def _deploy_call(calls: list[list[str]]) -> list[str]:
    return next(args for args in calls if args[:2] == ["run", "deploy"])


def _flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def _deployed_environment(args: list[str]) -> dict[str, str]:
    raw = _flag_value(args, "--set-env-vars")
    return dict(item.split("=", 1) for item in raw.split(","))


def test_cloud_run_deploy_default_preserves_private_offline_mode(
    tmp_path: Path,
) -> None:
    environment, log_path = _deploy_environment(tmp_path)

    result = _run_deploy(environment)

    assert result.returncode == 0, result.stderr
    assert "private offline API only" in result.stdout
    calls = _gcloud_calls(log_path)
    deploy = _deploy_call(calls)
    deployed = _deployed_environment(deploy)
    assert deployed["AUTONOMERCE_DEPLOYMENT_MODE"] == (
        "cloud-run-private-offline"
    )
    assert deployed["AUTONOMERCE_MODE"] == "offline"
    assert deployed["AUTONOMERCE_PAYMENT_MODE"] == "offline"
    assert deployed["AUTONOMERCE_PAYMENT_STORE_DURABILITY"] == "memory-offline"
    assert deployed["AUTONOMERCE_TRUSTED_HOSTS"] == (
        "autonomerce-api.example.run.app"
    )
    assert "AUTONOMERCE_GEMINI_MODEL" not in deployed
    assert "AUTONOMERCE_PRODUCTIZER_MODE" not in deployed
    assert _flag_value(deploy, "--set-secrets") == (
        "AUTONOMERCE_API_BEARER_TOKEN=api-bearer:7"
    )
    assert "--no-allow-unauthenticated" in deploy
    assert "--allow-unauthenticated" not in deploy
    assert _flag_value(deploy, "--concurrency") == "1"
    assert _flag_value(deploy, "--max-instances") == "1"
    assert _flag_value(deploy, "--min-instances") == "0"
    assert _flag_value(deploy, "--ingress") == "internal"
    assert _flag_value(deploy, "--service-account") == (
        environment["AUTONOMERCE_RUNTIME_SERVICE_ACCOUNT"]
    )
    assert _flag_value(deploy, "--labels") == (
        "autonomerce-exposure=private,autonomerce-payment=offline"
    )
    assert any(
        args[:4] == ["run", "services", "add-iam-policy-binding",
                     "autonomerce-api"]
        and _flag_value(args, "--member")
        == environment["AUTONOMERCE_ALLOWED_INVOKER"]
        for args in calls
    )


def test_cloud_run_deploy_supports_private_vertex_gemini_mode(
    tmp_path: Path,
) -> None:
    environment, log_path = _deploy_environment(tmp_path)
    environment.update(
        {
            "AUTONOMERCE_DEPLOYMENT_MODE": "cloud-run-private-gemini",
            "AUTONOMERCE_GEMINI_MODEL": "gemini-2.5-flash",
            "GOOGLE_CLOUD_LOCATION": "global",
        }
    )

    result = _run_deploy(environment)

    assert result.returncode == 0, result.stderr
    assert "private Gemini API with offline payment and fulfillment" in (
        result.stdout
    )
    deploy = _deploy_call(_gcloud_calls(log_path))
    deployed = _deployed_environment(deploy)
    assert deployed["AUTONOMERCE_DEPLOYMENT_MODE"] == (
        "cloud-run-private-gemini"
    )
    assert deployed["AUTONOMERCE_MODE"] == "gemini"
    assert deployed["AUTONOMERCE_PRODUCTIZER_MODE"] == "gemini"
    assert deployed["AUTONOMERCE_PAYMENT_MODE"] == "offline"
    assert deployed["AUTONOMERCE_PAYMENT_STORE_DURABILITY"] == "memory-offline"
    assert deployed["AUTONOMERCE_TRUSTED_HOSTS"] == (
        "autonomerce-api.example.run.app"
    )
    assert deployed["AUTONOMERCE_GEMINI_MODEL"] == "gemini-2.5-flash"
    assert deployed["GOOGLE_CLOUD_PROJECT"] == "autonomerce-test"
    assert deployed["GOOGLE_CLOUD_LOCATION"] == "global"
    assert deployed["GOOGLE_GENAI_USE_VERTEXAI"] == "true"
    assert _flag_value(deploy, "--set-secrets") == (
        "AUTONOMERCE_API_BEARER_TOKEN=api-bearer:7"
    )
    assert _flag_value(deploy, "--labels") == (
        "autonomerce-exposure=private,autonomerce-payment=offline,"
        "autonomerce-gemini=vertex"
    )
    assert _flag_value(deploy, "--concurrency") == "1"
    assert _flag_value(deploy, "--max-instances") == "1"
    assert _flag_value(deploy, "--min-instances") == "0"
    assert _flag_value(deploy, "--ingress") == "internal"
    assert _flag_value(deploy, "--service-account") == (
        environment["AUTONOMERCE_RUNTIME_SERVICE_ACCOUNT"]
    )
    assert "--no-allow-unauthenticated" in deploy
    assert any(
        args[:4]
        == [
            "run",
            "services",
            "add-iam-policy-binding",
            "autonomerce-api",
        ]
        and _flag_value(args, "--member")
        == environment["AUTONOMERCE_ALLOWED_INVOKER"]
        for args in _gcloud_calls(log_path)
    )


def test_cloud_run_deploy_rejects_gemini_mode_without_model(
    tmp_path: Path,
) -> None:
    environment, log_path = _deploy_environment(tmp_path)
    environment["AUTONOMERCE_DEPLOYMENT_MODE"] = (
        "cloud-run-private-gemini"
    )

    result = _run_deploy(environment)

    assert result.returncode == runtime_preflight.EXIT_BLOCKED
    assert "requires AUTONOMERCE_GEMINI_MODEL" in result.stderr
    assert _gcloud_calls(log_path) == []


def test_cloud_run_deploy_rejects_live_factory_in_gemini_mode(
    tmp_path: Path,
) -> None:
    environment, log_path = _deploy_environment(tmp_path)
    environment.update(
        {
            "AUTONOMERCE_DEPLOYMENT_MODE": "cloud-run-private-gemini",
            "AUTONOMERCE_GEMINI_MODEL": "gemini-2.5-flash",
            "AUTONOMERCE_SELLER_EXECUTOR_FACTORY": "autonomerce.live:build",
        }
    )

    result = _run_deploy(environment)

    assert result.returncode == runtime_preflight.EXIT_BLOCKED
    assert "keeps payment and fulfillment offline" in result.stderr
    assert _gcloud_calls(log_path) == []


@pytest.mark.parametrize(
    ("trusted_hosts", "private_origin"),
    [
        ("*", "https://autonomerce-api.example.run.app"),
        (
            "different-api.example.run.app",
            "https://autonomerce-api.example.run.app",
        ),
    ],
)
def test_cloud_run_deploy_rejects_untrusted_host_boundaries(
    tmp_path: Path,
    trusted_hosts: str,
    private_origin: str,
) -> None:
    environment, log_path = _deploy_environment(tmp_path)
    environment.update(
        {
            "AUTONOMERCE_API_PRIVATE_ORIGIN": private_origin,
            "AUTONOMERCE_DEPLOYMENT_MODE": "cloud-run-private-gemini",
            "AUTONOMERCE_GEMINI_MODEL": "gemini-2.5-flash",
            "AUTONOMERCE_TRUSTED_HOSTS": trusted_hosts,
        }
    )

    result = _run_deploy(environment)

    assert result.returncode == runtime_preflight.EXIT_BLOCKED
    assert _gcloud_calls(log_path) == []


def test_cloud_run_deploy_rejects_public_invoker_for_gemini_mode(
    tmp_path: Path,
) -> None:
    environment, log_path = _deploy_environment(tmp_path)
    environment.update(
        {
            "AUTONOMERCE_ALLOWED_INVOKER": "allUsers",
            "AUTONOMERCE_API_AUTH_MODE": "cloud-run-iam",
            "AUTONOMERCE_DEPLOYMENT_MODE": "cloud-run-private-gemini",
            "AUTONOMERCE_GEMINI_MODEL": "gemini-2.5-flash",
        }
    )

    result = _run_deploy(environment)

    assert result.returncode == runtime_preflight.EXIT_BLOCKED
    assert "public invoker principals are forbidden" in result.stderr
    assert _gcloud_calls(log_path) == []


def test_cloud_run_preflight_rejects_missing_application_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_runtime(
        monkeypatch,
        deployment_mode="cloud-run-private-gemini",
        runtime_mode="gemini",
    )
    _enable_vertex_gemini(monkeypatch)
    monkeypatch.delenv("AUTONOMERCE_API_BEARER_TOKEN")

    with pytest.raises(SystemExit) as exc_info:
        runtime_preflight.main()
    assert exc_info.value.code == runtime_preflight.EXIT_BLOCKED


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF",
            "",
            "must be set",
        ),
        (
            "AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF",
            "api-bearer:latest",
            "explicit numeric Secret Manager version",
        ),
        (
            "AUTONOMERCE_API_BEARER_TOKEN",
            "must-not-travel-on-the-command-line",
            "must not be passed directly",
        ),
    ],
)
def test_cloud_run_deploy_requires_secret_backed_application_bearer(
    tmp_path: Path,
    name: str,
    value: str,
    message: str,
) -> None:
    environment, log_path = _deploy_environment(tmp_path)
    if value:
        environment[name] = value
    else:
        environment.pop(name, None)

    result = _run_deploy(environment)

    assert result.returncode == runtime_preflight.EXIT_BLOCKED
    assert message in result.stderr
    assert _gcloud_calls(log_path) == []
