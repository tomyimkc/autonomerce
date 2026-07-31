from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_circle_testnet_order as script  # noqa: E402
from autonomerce.payments import (  # noqa: E402
    ARC_TESTNET_USDC,
    ExecutionResult,
    PaymentMode,
    SQLitePaymentStore,
)


PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
TX_HASH = "0x" + ("a" * 64)


def _config(
    tmp_path: Path,
    *,
    binary: Path | None = None,
    interpreter: Path | None = None,
) -> script.RunConfiguration:
    selected_binary = binary or (tmp_path / "circle")
    return script.RunConfiguration(
        order_id="order-arc-proof-001",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        circle_cli_binary=selected_binary,
        circle_cli_sha256=(
            hashlib.sha256(selected_binary.read_bytes()).hexdigest()
            if selected_binary.exists()
            else "1" * 64
        ),
        sqlite_path=tmp_path / "payments.sqlite3",
        evidence_path=tmp_path / "transaction.public.json",
        circle_cli_interpreter=interpreter,
        circle_cli_interpreter_sha256=(
            hashlib.sha256(interpreter.read_bytes()).hexdigest()
            if interpreter is not None and interpreter.exists()
            else None
        ),
    )


def test_dry_run_preflights_pinned_cli_without_transfer_or_evidence(tmp_path):
    binary = tmp_path / "circle"
    binary.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    binary.chmod(0o700)
    config = _config(tmp_path, binary=binary)

    result = script.run_order(
        config,
        dry_run=True,
        confirmation=None,
    )

    assert result["mode"] == "dry-run"
    assert result["transferExecuted"] is False
    assert result["transferAuthorized"] is False
    assert result["policyWouldAuthorize"] is True
    assert result["proposalState"] == "accepted"
    assert result["amountUsdc"] == "0.1"
    assert result["maximumPerPaymentUsdc"] == "0.1"
    assert result["maximumTotalUsdc"] == "0.2"
    assert result["maximumPaymentCount"] == 2
    assert result["countedAsRevenue"] is False
    assert not config.evidence_path.exists()
    assert SQLitePaymentStore(config.sqlite_path).list() == ()


def test_non_dry_run_requires_the_exact_confirmation_before_setup(tmp_path):
    config = _config(tmp_path)
    called = False

    def forbidden_executor(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("executor factory must not be reached")

    with pytest.raises(ValueError, match="exact Arc testnet"):
        script.run_order(
            config,
            dry_run=False,
            confirmation="yes",
            executor_factory=forbidden_executor,
        )

    assert called is False
    assert not config.sqlite_path.exists()
    assert not config.evidence_path.exists()


def test_build_executor_forwards_paired_interpreter_pins(tmp_path):
    interpreter = tmp_path / "node"
    interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    interpreter.chmod(0o700)
    cli_script = tmp_path / "circle.js"
    cli_script.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    cli_script.chmod(0o700)
    config = _config(
        tmp_path,
        binary=cli_script,
        interpreter=interpreter,
    )
    captured = {}
    sentinel = object()

    def executor_factory(**kwargs):
        captured.update(kwargs)
        return sentinel

    assert (
        script._build_executor(
            config,
            executor_factory=executor_factory,
        )
        is sentinel
    )
    assert captured == {
        "mode": PaymentMode.TESTNET,
        "binary": str(cli_script),
        "binary_sha256": config.circle_cli_sha256,
        "working_directory": "/",
        "interpreter_binary": str(interpreter),
        "interpreter_sha256": config.circle_cli_interpreter_sha256,
    }


def test_exact_confirmation_executes_once_replays_and_writes_redacted_evidence(
    tmp_path,
):
    executor_calls: list[object] = []
    constructor_kwargs: list[dict[str, object]] = []

    class FakeExecutor:
        mode = PaymentMode.TESTNET

        def build_argv(self, intent):
            assert intent.amount_usdc == Decimal("0.10")
            assert intent.chain == "ARC-TESTNET"
            assert intent.asset == ARC_TESTNET_USDC
            return ["circle", "wallet", "transfer"]

        def execute(self, intent):
            executor_calls.append(intent)
            return ExecutionResult(
                state="CONFIRMED",
                amount_usdc=intent.amount_usdc,
                chain=intent.chain,
                payer_wallet=intent.payer_wallet,
                payee_wallet=intent.payee_wallet,
                transaction_hash=TX_HASH,
                confirmed_at="2026-07-31T12:00:00Z",
                explorer_url=None,
                simulated=False,
                provider_reference="mocked-circle-testnet",
                token=intent.token,
                asset=intent.asset,
            )

    def executor_factory(**kwargs):
        constructor_kwargs.append(kwargs)
        return FakeExecutor()

    def lookup_factory():
        def lookup(transaction_hash: str):
            return {
                "confirmed": True,
                "chain": "ARC-TESTNET",
                "amountUsdc": "0.1",
                "payerWallet": PAYER,
                "payeeWallet": PAYEE,
                "transactionHash": transaction_hash,
                "token": "USDC",
                "asset": ARC_TESTNET_USDC,
            }

        return lookup

    config = _config(tmp_path)
    result = script.run_order(
        config,
        dry_run=False,
        confirmation=script.TRANSFER_CONFIRMATION,
        executor_factory=executor_factory,
        lookup_factory=lookup_factory,
    )

    assert result["mode"] == "testnet-transfer"
    assert result["transferExecuted"] is True
    assert result["idempotentReplayVerified"] is True
    assert result["transactionHash"] == TX_HASH
    assert result["countedAsRevenue"] is False
    assert len(executor_calls) == 1
    assert constructor_kwargs == [
        {
            "mode": PaymentMode.TESTNET,
            "binary": str(config.circle_cli_binary),
            "binary_sha256": config.circle_cli_sha256,
            "working_directory": "/",
        }
    ]

    store = SQLitePaymentStore(config.sqlite_path)
    records = store.list()
    assert len(records) == 1
    assert records[0].transaction_hash == TX_HASH

    evidence = json.loads(config.evidence_path.read_text(encoding="utf-8"))
    assert evidence["evidenceClassification"] == "testnet"
    assert evidence["movesFunds"] is True
    assert evidence["transactionHash"] == TX_HASH
    assert evidence["payerWallet"] is None
    assert evidence["payeeWallet"] is None
    assert evidence["countedAsRevenue"] is False
    assert evidence["orderId"] != config.order_id
    assert all("idempotency" not in key.lower() for key in evidence)
    assert config.order_id not in json.dumps(evidence)
    assert PAYER.lower() not in json.dumps(evidence).lower()
    assert PAYEE.lower() not in json.dumps(evidence).lower()
    permissions = stat.S_IMODE(config.evidence_path.stat().st_mode)
    assert permissions == 0o600


def test_cli_dry_run_accepts_paired_pinned_interpreter(
    tmp_path,
    capsys,
):
    interpreter = tmp_path / "node"
    interpreter.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    interpreter.chmod(0o700)
    cli_script = tmp_path / "circle.js"
    cli_script.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    cli_script.chmod(0o700)
    database = tmp_path / "payments.sqlite3"
    evidence = tmp_path / "evidence.json"

    assert (
        script.main(
            [
                "--dry-run",
                "--order-id",
                "order-interpreter-preflight",
                "--payer-wallet",
                PAYER,
                "--payee-wallet",
                PAYEE,
                "--circle-cli-binary",
                str(cli_script),
                "--circle-cli-sha256",
                hashlib.sha256(cli_script.read_bytes()).hexdigest(),
                "--circle-cli-interpreter",
                str(interpreter),
                "--circle-cli-interpreter-sha256",
                hashlib.sha256(interpreter.read_bytes()).hexdigest(),
                "--sqlite-path",
                str(database),
                "--evidence-path",
                str(evidence),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["interpreterPinned"] is True
    assert output["transferExecuted"] is False
    assert SQLitePaymentStore(database).list() == ()
    assert not evidence.exists()


@pytest.mark.parametrize(
    "interpreter_args",
    [
        ["--circle-cli-interpreter", "/absolute/node"],
        ["--circle-cli-interpreter-sha256", "1" * 64],
    ],
)
def test_cli_requires_interpreter_path_and_sha_pair(
    tmp_path,
    interpreter_args,
):
    database = tmp_path / "payments.sqlite3"
    evidence = tmp_path / "evidence.json"
    with pytest.raises(SystemExit) as failure:
        script.main(
            [
                "--dry-run",
                "--order-id",
                "order-1",
                "--payer-wallet",
                PAYER,
                "--payee-wallet",
                PAYEE,
                "--circle-cli-binary",
                str(tmp_path / "circle"),
                "--circle-cli-sha256",
                "1" * 64,
                *interpreter_args,
                "--sqlite-path",
                str(database),
                "--evidence-path",
                str(evidence),
            ]
        )

    assert failure.value.code == 2
    assert not database.exists()
    assert not evidence.exists()


def test_cli_rejects_inexact_confirmation_flag_before_transfer_setup(tmp_path):
    database = tmp_path / "payments.sqlite3"
    evidence = tmp_path / "evidence.json"
    with pytest.raises(SystemExit) as failure:
        script.main(
            [
                "--confirm-testnet-transfer",
                "EXECUTE_ARC_TESTNET_USDC_TRANSFER",
                "--order-id",
                "order-1",
                "--payer-wallet",
                PAYER,
                "--payee-wallet",
                PAYEE,
                "--circle-cli-binary",
                str(tmp_path / "circle"),
                "--circle-cli-sha256",
                "1" * 64,
                "--sqlite-path",
                str(database),
                "--evidence-path",
                str(evidence),
            ]
        )

    assert failure.value.code == 2
    assert not database.exists()
    assert not evidence.exists()
