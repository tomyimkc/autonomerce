#!/usr/bin/env python3
"""Fail-closed deployment checks before starting the Autonomerce API.

This module does not add application-level authorization. It prevents the container
from starting when the declared deployment boundary, payment mode, external auth
mode, or payment-store configuration is inconsistent.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from importlib import import_module
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse


EXIT_BLOCKED = 2
MAINNET_CONFIRMATION = "ENABLE_REAL_MAINNET_PAYMENTS"

MODE_PAYMENT = {
    "local-offline": "offline",
    "cloud-run-private-offline": "offline",
    "private-single-host-testnet": "testnet",
    "private-single-host-mainnet": "mainnet",
}

MODE_RUNTIME = {
    "local-offline": "offline",
    "cloud-run-private-offline": "offline",
    "private-single-host-testnet": "live",
    "private-single-host-mainnet": "live",
}

CLOUD_RUN_AUTH_MODES = {
    "cloud-run-iam",
    "iap",
    "service-to-service",
}

PROTECTED_AUTH_MODES = CLOUD_RUN_AUTH_MODES | {"external-auth-proxy"}

LEGACY_PAYMENT_ENV = {
    "AUTONOMERCE_PUBLIC_BASE_URL",
    "AUTONOMERCE_CIRCLE_NETWORK",
    "AUTONOMERCE_CIRCLE_WALLET_ADDRESS",
    "AUTONOMERCE_CIRCLE_MAX_PER_TX_USDC",
    "AUTONOMERCE_CIRCLE_MAX_DAILY_USDC",
}

FORBIDDEN_DURABLE_ROOTS = tuple(
    Path(path).resolve()
    for path in (
        "/app",
        "/home",
        "/tmp",
        "/var/tmp",
        "/workspace",
    )
)


def blocked(message: str) -> "NoReturn":
    print(f"BLOCKED: {message}", file=sys.stderr)
    raise SystemExit(EXIT_BLOCKED)


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        blocked(f"{name} must be set explicitly")
    return value


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_origin(name: str, *, https_required: bool) -> str:
    value = required(name)
    parsed = urlparse(value)
    allowed_schemes = {"https"} if https_required else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        expected = "https" if https_required else "http or https"
        blocked(f"{name} must be an absolute {expected} origin")
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        blocked(f"{name} must be an origin without a path, query, or fragment")
    return f"{parsed.scheme}://{parsed.netloc}"


def positive_decimal(name: str) -> Decimal:
    value = required(name)
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        blocked(f"{name} must be an exact decimal value ({exc})")
    if not parsed.is_finite() or parsed <= 0:
        blocked(f"{name} must be finite and greater than zero")
    if -parsed.as_tuple().exponent > 6:
        blocked(f"{name} must use at most six decimal places")
    return parsed


def positive_int(name: str) -> int:
    value = required(name)
    try:
        parsed = int(value)
    except ValueError as exc:
        blocked(f"{name} must be an integer ({exc})")
    if parsed < 1:
        blocked(f"{name} must be at least 1")
    return parsed


def validate_publication_configuration() -> None:
    mode = required("AUTONOMERCE_RECEIPT_PUBLICATION_MODE").lower()
    if mode not in {"disabled", "verified"}:
        blocked(
            "AUTONOMERCE_RECEIPT_PUBLICATION_MODE must be disabled or verified"
        )
    factory_path = os.environ.get(
        "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY", ""
    ).strip()
    if mode == "disabled":
        if factory_path:
            blocked(
                "publication verifier factory must be unset when receipt "
                "publication is disabled"
            )
        return
    if not factory_path or ":" not in factory_path:
        blocked(
            "verified receipt publication requires "
            "AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY=module:function"
        )
    module_name, attribute = factory_path.rsplit(":", 1)
    try:
        factory = getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        blocked(
            "publication consent verifier factory could not be imported: "
            f"{type(exc).__name__}"
        )
    if not callable(factory):
        blocked("publication consent verifier factory is not callable")
    try:
        verifier = factory()
    except Exception as exc:  # noqa: BLE001 - startup must fail closed
        blocked(
            "publication consent verifier factory failed: "
            f"{type(exc).__name__}"
        )
    if not callable(verifier):
        blocked(
            "publication consent verifier factory must return a callable"
        )


def validate_live_store() -> None:
    if required("AUTONOMERCE_PAYMENT_STORE_DURABILITY") != (
        "single-host-persistent-volume"
    ):
        blocked(
            "non-offline modes require "
            "AUTONOMERCE_PAYMENT_STORE_DURABILITY="
            "single-host-persistent-volume"
        )

    root = Path(required("AUTONOMERCE_PAYMENT_DURABLE_MOUNT_PATH")).resolve()
    payment_database = Path(
        required("AUTONOMERCE_PAYMENT_SQLITE_PATH")
    ).resolve()
    commerce_database = Path(
        required("AUTONOMERCE_COMMERCE_SQLITE_PATH")
    ).resolve()
    if (
        not root.is_absolute()
        or not payment_database.is_absolute()
        or not commerce_database.is_absolute()
    ):
        blocked("durable mount and both SQLite paths must be absolute")
    if any(
        root == forbidden or is_within(root, forbidden)
        for forbidden in FORBIDDEN_DURABLE_ROOTS
    ):
        blocked(f"durable payment storage cannot use ephemeral path {root}")
    if payment_database == root or not is_within(payment_database, root):
        blocked("AUTONOMERCE_PAYMENT_SQLITE_PATH must be inside the durable mount")
    if commerce_database == root or not is_within(commerce_database, root):
        blocked(
            "AUTONOMERCE_COMMERCE_SQLITE_PATH must be inside the durable mount"
        )
    if commerce_database != payment_database:
        blocked(
            "single-host live mode requires commerce and payment state to share "
            "one SQLite database for crash reconciliation"
        )
    if not root.is_dir():
        blocked(f"durable payment mount does not exist: {root}")
    if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
        blocked(f"durable payment mount is not readable/writable: {root}")

    marker = root / ".autonomerce-durable-volume"
    try:
        marker_value = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        blocked(f"durable payment mount marker is missing or unreadable: {exc}")
    if marker_value != "AUTONOMERCE_DURABLE_STORE_V1":
        blocked("durable payment mount marker has unexpected content")


def validate_live_payment(mode: str, *, on_cloud_run: bool) -> None:
    if not required("AUTONOMERCE_API_OWNER_ID"):
        blocked("non-offline mode requires an explicit API owner ID")
    if not required("AUTONOMERCE_API_BEARER_TOKEN"):
        blocked("non-offline mode requires application bearer authentication")
    if required("AUTONOMERCE_API_WORKERS") != "1":
        blocked("single-host SQLite live mode requires AUTONOMERCE_API_WORKERS=1")
    if not required("AUTONOMERCE_GEMINI_MODEL"):
        blocked("non-offline mode requires an explicit Gemini model")
    if not required("AUTONOMERCE_SELLER_EXECUTOR_FACTORY"):
        blocked("non-offline mode requires a seller-agent executor factory")
    if not required("AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY"):
        blocked(
            "non-offline mode requires an independent transaction lookup factory"
        )
    validate_publication_configuration()

    if on_cloud_run:
        blocked(
            "testnet/mainnet payment mode is not supported on Cloud Run: the "
            "current adapter only provides SQLite, Cloud Run local storage is "
            "ephemeral, and Cloud Run NFS volumes do not provide file locking. "
            "Implement a shared managed durable-store adapter first"
        )

    validate_live_store()

    if not required("AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS"):
        blocked("live payment mode requires an explicit payer-wallet allowlist")
    if not required("AUTONOMERCE_PAYMENT_ALLOWED_PAYEE_WALLETS"):
        blocked("live payment mode requires an explicit payee-wallet allowlist")

    chains = {
        item.strip().upper()
        for item in required("AUTONOMERCE_PAYMENT_ALLOWED_CHAINS").split(",")
        if item.strip()
    }
    expected_chains = (
        {"ARC-TESTNET", "BASE-SEPOLIA"} if mode == "testnet" else {"BASE"}
    )
    if not chains or not chains.issubset(expected_chains):
        blocked(
            "payment chain allowlist is inconsistent with "
            f"{mode} mode; expected a subset of {sorted(expected_chains)}"
        )

    per_payment = positive_decimal(
        "AUTONOMERCE_PAYMENT_MAX_PER_PAYMENT_USDC"
    )
    total = positive_decimal("AUTONOMERCE_PAYMENT_MAX_TOTAL_USDC")
    positive_int("AUTONOMERCE_PAYMENT_MAX_COUNT")
    if total < per_payment:
        blocked("total USDC cap must be greater than or equal to the per-payment cap")

    binary = required("AUTONOMERCE_CIRCLE_CLI_BINARY")
    binary_path = Path(binary)
    if (
        any(character.isspace() for character in binary)
        or not binary_path.is_absolute()
    ):
        blocked("AUTONOMERCE_CIRCLE_CLI_BINARY must be one absolute argv path")
    if shutil.which(binary) is None:
        blocked(f"Circle CLI executable is not available: {binary}")
    binary_sha256 = required("AUTONOMERCE_CIRCLE_CLI_SHA256").lower()
    if not re.fullmatch(r"[a-f0-9]{64}", binary_sha256):
        blocked(
            "AUTONOMERCE_CIRCLE_CLI_SHA256 must be 64 lowercase hexadecimal characters"
        )

    if mode == "mainnet":
        if os.environ.get("AUTONOMERCE_ENABLE_MAINNET_PAYMENTS") != MAINNET_CONFIRMATION:
            blocked(
                "mainnet requires AUTONOMERCE_ENABLE_MAINNET_PAYMENTS="
                f"{MAINNET_CONFIRMATION}"
            )

    try:
        from autonomerce.api.sqlite_repository import SQLiteRepository
        from autonomerce.payments.api_adapter import build_payment_adapter
        from autonomerce.payments.store import SQLitePaymentStore

        adapter = build_payment_adapter(dict(os.environ))
        commerce_repository = SQLiteRepository(
            Path(required("AUTONOMERCE_COMMERCE_SQLITE_PATH"))
        )
        commerce_repository.close()
    except Exception as exc:  # noqa: BLE001 - startup must fail closed on any adapter error
        blocked(f"payment adapter construction failed: {type(exc).__name__}: {exc}")
    if adapter.mode.value != mode:
        blocked("constructed payment adapter mode does not match the declared mode")
    if not isinstance(adapter.store, SQLitePaymentStore):
        blocked("non-offline payment adapter did not construct the required SQLite store")

    if not getattr(adapter.store, "durability", None):
        blocked("payment store does not declare durability")


def main() -> int:
    legacy = sorted(name for name in LEGACY_PAYMENT_ENV if name in os.environ)
    if legacy:
        blocked(
            "legacy/ignored environment variables are set: "
            + ", ".join(legacy)
            + "; use AUTONOMERCE_PAYMENT_* names"
        )

    deployment_mode = required("AUTONOMERCE_DEPLOYMENT_MODE")
    if deployment_mode not in MODE_PAYMENT:
        blocked(
            "AUTONOMERCE_DEPLOYMENT_MODE must be one of "
            + ", ".join(sorted(MODE_PAYMENT))
        )

    payment_mode = required("AUTONOMERCE_PAYMENT_MODE").lower()
    expected_payment_mode = MODE_PAYMENT[deployment_mode]
    if payment_mode != expected_payment_mode:
        blocked(
            f"{deployment_mode} requires AUTONOMERCE_PAYMENT_MODE="
            f"{expected_payment_mode}, not {payment_mode}"
        )

    runtime_mode = required("AUTONOMERCE_MODE").lower()
    expected_runtime_mode = MODE_RUNTIME[deployment_mode]
    if runtime_mode != expected_runtime_mode:
        blocked(
            f"{deployment_mode} requires AUTONOMERCE_MODE="
            f"{expected_runtime_mode}, not {runtime_mode}"
        )

    auth_mode = required("AUTONOMERCE_API_AUTH_MODE")
    on_cloud_run = bool(os.environ.get("K_SERVICE"))
    cloud_run_mode = deployment_mode.startswith("cloud-run-")

    if cloud_run_mode and not on_cloud_run:
        blocked("cloud-run deployment mode requires the K_SERVICE runtime marker")
    if on_cloud_run and not cloud_run_mode:
        blocked("Cloud Run must use an explicit cloud-run-private-* deployment mode")

    protected = deployment_mode != "local-offline"
    if protected and auth_mode not in PROTECTED_AUTH_MODES:
        blocked("private API modes require an external authenticated access mode")
    if not protected and auth_mode != "local-only":
        blocked("local-offline mode requires AUTONOMERCE_API_AUTH_MODE=local-only")
    if cloud_run_mode and auth_mode not in CLOUD_RUN_AUTH_MODES:
        blocked(
            "Cloud Run requires cloud-run-iam, iap, or service-to-service auth"
        )

    web_origin = validate_origin(
        "AUTONOMERCE_WEB_PUBLIC_ORIGIN", https_required=protected
    )
    api_origin = validate_origin(
        "AUTONOMERCE_API_PRIVATE_ORIGIN", https_required=protected
    )
    if web_origin == api_origin:
        blocked("public web and private API origins must be separate")

    if payment_mode == "offline":
        if required("AUTONOMERCE_PAYMENT_STORE_DURABILITY") != "memory-offline":
            blocked("offline mode requires payment-store durability=memory-offline")
    else:
        validate_live_payment(payment_mode, on_cloud_run=on_cloud_run)

    print(
        "AUTONOMERCE RUNTIME PREFLIGHT: PASS "
        f"(deployment={deployment_mode}, runtime={runtime_mode}, "
        f"auth={auth_mode}, payment={payment_mode})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
