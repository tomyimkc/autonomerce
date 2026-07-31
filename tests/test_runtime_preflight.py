from __future__ import annotations

import importlib.util
from pathlib import Path
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
