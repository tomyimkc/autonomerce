from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.contracts import (  # noqa: E402
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
)
from autonomerce.payments import (  # noqa: E402
    MAINNET_CONFIRMATION,
    CircleCLIExecutor,
    CircleExecutionError,
    ExecutionResult,
    InMemoryPaymentStore,
    OfflineCircleExecutor,
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    PaymentPolicyDenied,
    PaymentPolicyGate,
    PaymentProcessor,
    PaymentReplayError,
    PaymentValidationError,
    ReceiptVerificationError,
    SQLitePaymentStore,
    StoreDurability,
    X402ParseError,
    parse_x402_payment_requirement,
    public_payment_receipt,
    redact_headers,
    verify_receipt,
    transaction_lookup_hook,
)
from autonomerce.payments.api_adapter import (  # noqa: E402
    PaymentAdapter as APIPaymentAdapter,
    build_payment_adapter,
)


PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
OTHER_PAYEE = "0x3333333333333333333333333333333333333333"
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
TX_HASH = "0x" + ("a" * 64)
REQUIREMENT_FINGERPRINT = "b" * 64
FIXED_TIME = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def proposal(
    *,
    proposal_id: str = "proposal_1",
    price: str = "1",
    state: ProposalState = ProposalState.ACCEPTED,
) -> Proposal:
    return Proposal(
        proposal_id=proposal_id,
        seller_agent_url="https://seller.example/agent-card.json",
        buyer_agent_url="https://buyer.example/agent-card.json",
        sku_id="sku_1",
        problem_observed="Buyer requested a verification",
        offered_outcome="Return a verification result",
        price_usdc=Decimal(price),
        delivery_seconds=60,
        state=state,
    )


def intent(
    *,
    proposal_id: str = "proposal_1",
    key: str = "idem-1",
    amount: str = "1",
    chain: str = "ARC-TESTNET",
    token: str = "USDC",
    payer: str = PAYER,
    payee: str = PAYEE,
    expected_amount: str | None = None,
    proposal_state: ProposalState = ProposalState.ACCEPTED,
    requirement_id: str | None = None,
    requirement_fingerprint: str | None = None,
    asset: str | None = None,
) -> PaymentIntent:
    return PaymentIntent(
        proposal_id=proposal_id,
        idempotency_key=key,
        amount_usdc=Decimal(amount),
        expected_amount_usdc=(
            Decimal(expected_amount) if expected_amount is not None else None
        ),
        proposal_state=proposal_state,
        chain=chain,
        token=token,
        payer_wallet=payer,
        payee_wallet=payee,
        x402_requirement_id=requirement_id,
        x402_requirement_fingerprint=requirement_fingerprint,
        asset=asset,
    )


def policy(
    *,
    mode: PaymentMode = PaymentMode.OFFLINE,
    per_payment: str = "2",
    total: str = "5",
    chains: tuple[str, ...] = ("ARC-TESTNET",),
    payees: tuple[str, ...] = (PAYEE,),
    mainnet_enabled: bool = False,
    assets: dict[str, tuple[str, ...]] | None = None,
) -> PaymentPolicy:
    return PaymentPolicy(
        policy_id="payment-policy-1",
        mode=mode,
        maximum_per_payment_usdc=Decimal(per_payment),
        maximum_total_usdc=Decimal(total),
        allowed_chains=chains,
        allowed_token="USDC",
        allowed_payer_wallets=(PAYER,),
        allowed_payee_wallets=payees,
        mainnet_enabled=mainnet_enabled,
        allowed_assets_by_chain=assets or {},
    )


def test_policy_gate_authorizes_only_exact_accepted_proposal():
    gate = PaymentPolicyGate()
    allowed = gate.evaluate(intent(), policy())
    assert allowed.authorized
    assert allowed.reason_code == "authorized"

    amount_mismatch = gate.evaluate(
        intent(amount="1", expected_amount="0.9"),
        policy(),
    )
    assert not amount_mismatch.authorized
    assert amount_mismatch.reason_code == "proposal_amount_mismatch"

    draft = gate.evaluate(
        intent(proposal_state=ProposalState.DRAFT),
        policy(),
    )
    assert not draft.authorized
    assert draft.reason_code == "proposal_not_accepted"


@pytest.mark.parametrize(
    ("changed_intent", "changed_policy", "reason"),
    [
        (
            {"amount": "2.1"},
            {"per_payment": "2"},
            "per_payment_limit",
        ),
        (
            {"chain": "BASE"},
            {},
            "chain_not_allowed",
        ),
        (
            {"token": "EURC"},
            {},
            "token_mismatch",
        ),
        (
            {"payee": OTHER_PAYEE},
            {},
            "payee_not_allowed",
        ),
        (
            {"payee": PAYER},
            {"payees": (PAYER,)},
            "self_payment",
        ),
    ],
)
def test_policy_gate_fails_closed_on_limits_chain_token_and_wallet(
    changed_intent, changed_policy, reason
):
    decision = PaymentPolicyGate().evaluate(
        intent(**changed_intent),
        policy(**changed_policy),
    )
    assert not decision.authorized
    assert decision.reason_code == reason


def test_policy_store_checks_cumulative_limit_atomically():
    store = InMemoryPaymentStore()
    bounded = policy(per_payment="2", total="2.5")
    store.reserve(intent(key="idem-total-1", amount="2"), bounded)
    with pytest.raises(PaymentPolicyDenied) as denied:
        store.reserve(
            intent(proposal_id="proposal_2", key="idem-total-2", amount="1"),
            bounded,
        )
    assert denied.value.reason_code == "cumulative_limit"
    assert len(store.list()) == 1


def test_mainnet_requires_policy_and_executor_opt_in():
    mainnet_intent = intent(chain="BASE", asset=BASE_USDC)
    disabled = policy(
        mode=PaymentMode.MAINNET,
        chains=("BASE",),
        mainnet_enabled=False,
    )
    decision = PaymentPolicyGate().evaluate(mainnet_intent, disabled)
    assert not decision.authorized
    assert decision.reason_code == "mainnet_not_enabled"

    with pytest.raises(PaymentValidationError):
        CircleCLIExecutor(mode=PaymentMode.MAINNET)

    executor = CircleCLIExecutor(
        mode=PaymentMode.MAINNET,
        allow_mainnet=True,
        mainnet_confirmation=MAINNET_CONFIRMATION,
        runner=lambda *args, **kwargs: None,  # never called
    )
    assert executor.mode is PaymentMode.MAINNET


@pytest.mark.parametrize(
    "wallet",
    [
        "",
        "not-an-address",
        "0x1234",
        "0x" + ("0" * 40),
        "0x" + ("g" * 40),
    ],
)
def test_payment_intent_rejects_malformed_or_zero_wallet(wallet):
    with pytest.raises(PaymentValidationError):
        intent(payee=wallet)


def test_in_memory_store_is_idempotent_and_rejects_key_replay():
    store = InMemoryPaymentStore()
    first = store.reserve(intent(), policy())
    same = store.reserve(intent(), policy())
    assert first.created
    assert not same.created
    assert same.receipt == first.receipt
    assert len(store.list()) == 1

    with pytest.raises(PaymentReplayError):
        store.reserve(intent(amount="1.1"), policy())

    with pytest.raises(PaymentReplayError):
        store.reserve(intent(key="different-key"), policy())


def test_x402_identifier_and_transaction_hash_cannot_be_replayed():
    store = InMemoryPaymentStore()
    store.reserve(
        intent(
            key="idem-x402-1",
            requirement_id="payment-identifier-1",
            requirement_fingerprint=REQUIREMENT_FINGERPRINT,
        ),
        policy(),
    )
    with pytest.raises(PaymentReplayError):
        store.reserve(
            intent(
                proposal_id="proposal_2",
                key="idem-x402-2",
                requirement_id="payment-identifier-1",
                requirement_fingerprint=REQUIREMENT_FINGERPRINT,
            ),
            policy(),
        )

    store = InMemoryPaymentStore()
    store.reserve(intent(proposal_id="proposal_tx_1", key="idem-tx-1"), policy())
    store.reserve(intent(proposal_id="proposal_tx_2", key="idem-tx-2"), policy())
    store.transition("idem-tx-1", PaymentState.SUBMITTING)
    store.transition("idem-tx-2", PaymentState.SUBMITTING)
    store.transition(
        "idem-tx-1",
        PaymentState.CONFIRMED,
        transaction_hash=TX_HASH,
    )
    with pytest.raises(PaymentReplayError):
        store.transition(
            "idem-tx-2",
            PaymentState.CONFIRMED,
            transaction_hash=TX_HASH,
        )


def test_sqlite_store_preserves_idempotency_across_instances(tmp_path):
    database = tmp_path / "payments.sqlite3"
    first_store = SQLitePaymentStore(database)
    first = first_store.reserve(intent(), policy())
    assert first.created

    reopened = SQLitePaymentStore(database)
    duplicate = reopened.reserve(intent(), policy())
    assert not duplicate.created
    assert duplicate.receipt.payment_id == first.receipt.payment_id
    assert reopened.snapshot("payment-policy-1").committed_usdc == Decimal("1")


def test_offline_processor_is_deterministic_and_executes_once():
    store = InMemoryPaymentStore()
    executor = OfflineCircleExecutor(clock=lambda: FIXED_TIME)
    processor = PaymentProcessor(policy=policy(), store=store, executor=executor)

    first = processor.pay(intent())
    duplicate = processor.pay(intent())

    assert first.state is PaymentState.CONFIRMED
    assert first.transaction_hash == duplicate.transaction_hash
    assert first.confirmed_at == "2026-07-31T12:00:00Z"
    assert len(executor.calls) == 1


def test_api_adapter_defaults_offline_and_never_submits_real_payment():
    adapter = build_payment_adapter({})
    assert isinstance(adapter, APIPaymentAdapter)
    assert adapter.mode is PaymentMode.OFFLINE
    execution = adapter.execute_payment(
        proposal(),
        idempotency_key="api-adapter-idem-1",
        chain="ARC-TESTNET",
        token="USDC",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        public=False,
    )
    assert execution.mocked
    assert execution.receipt.state is PaymentState.CONFIRMED
    assert isinstance(adapter.executor, OfflineCircleExecutor)


def test_live_adapter_rejects_process_local_store_and_exposes_durability(tmp_path):
    with pytest.raises(PaymentValidationError, match="process-local"):
        APIPaymentAdapter(
            mode=PaymentMode.TESTNET,
            store=InMemoryPaymentStore(),
            allowed_payer_wallets=(PAYER,),
            allowed_payee_wallets=(PAYEE,),
        )

    adapter = APIPaymentAdapter(
        mode=PaymentMode.TESTNET,
        store=SQLitePaymentStore(tmp_path / "payments.sqlite3"),
        executor=CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            runner=lambda *args, **kwargs: None,
        ),
        allowed_payer_wallets=(PAYER,),
        allowed_payee_wallets=(PAYEE,),
        verification_hooks=(transaction_lookup_hook(lambda _: None),),
    )
    assert adapter.durability is StoreDurability.SINGLE_NODE
    assert adapter.store.durability is StoreDurability.SINGLE_NODE


def test_live_adapter_confirms_only_after_independent_asset_lookup(tmp_path):
    lookup_calls: list[str] = []

    def runner(argv, **kwargs):
        payload = {
            "data": {
                "id": "circle-transfer-verified",
                "state": "CONFIRMED",
                "blockchain": "ARC-TESTNET",
                "amounts": ["1"],
                "sourceAddress": PAYER,
                "destinationAddress": PAYEE,
                "txHash": TX_HASH,
                "updateDate": "2026-07-31T12:00:00Z",
            }
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    def lookup(transaction_hash: str):
        lookup_calls.append(transaction_hash)
        return {
            "confirmed": True,
            "chain": "ARC-TESTNET",
            "amountUsdc": "1",
            "payerWallet": PAYER,
            "payeeWallet": PAYEE,
            "transactionHash": transaction_hash,
            "token": "USDC",
            "asset": "0x3600000000000000000000000000000000000000",
        }

    adapter = APIPaymentAdapter(
        mode=PaymentMode.TESTNET,
        store=SQLitePaymentStore(tmp_path / "payments.sqlite3"),
        executor=CircleCLIExecutor(
            mode=PaymentMode.TESTNET,
            runner=runner,
        ),
        allowed_payer_wallets=(PAYER,),
        allowed_payee_wallets=(PAYEE,),
        verification_hooks=(transaction_lookup_hook(lookup),),
    )
    execution = adapter.execute_payment(
        proposal(),
        idempotency_key="live-independent-lookup",
        chain="ARC-TESTNET",
        token="USDC",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        public=False,
    )

    assert execution.receipt.state is PaymentState.CONFIRMED
    assert (
        execution.receipt.asset
        == "0x3600000000000000000000000000000000000000"
    )
    assert lookup_calls == [TX_HASH]


def test_documented_circle_environment_maps_to_live_payment_policy(tmp_path):
    executable = tmp_path / "circle"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    adapter = build_payment_adapter(
        {
            "AUTONOMERCE_MODE": "live",
            "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
            "AUTONOMERCE_CIRCLE_WALLET_ADDRESS": PAYER,
            "AUTONOMERCE_CIRCLE_MAX_PER_TX_USDC": "1",
            "AUTONOMERCE_CIRCLE_MAX_DAILY_USDC": "10",
            "AUTONOMERCE_PAYMENT_ALLOWED_PAYEE_WALLETS": PAYEE,
            "AUTONOMERCE_PAYMENT_SQLITE_PATH": str(
                tmp_path / "payments.sqlite3"
            ),
            "AUTONOMERCE_CIRCLE_CLI_BINARY": str(executable),
            "AUTONOMERCE_CIRCLE_CLI_SHA256": hashlib.sha256(
                executable.read_bytes()
            ).hexdigest(),
        },
        transaction_lookup=lambda _: None,
    )
    assert adapter.mode is PaymentMode.TESTNET
    assert adapter.maximum_per_payment_usdc == Decimal("1")
    assert adapter.maximum_total_usdc == Decimal("10")
    assert adapter.allowed_chains == ("ARC-TESTNET",)
    assert adapter.allowed_payer_wallets == (PAYER,)
    assert adapter.durability is StoreDurability.SINGLE_NODE


def test_canonical_live_environment_uses_explicit_payment_mode(tmp_path):
    executable = tmp_path / "circle"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    adapter = build_payment_adapter(
        {
            "AUTONOMERCE_MODE": "live",
            "AUTONOMERCE_PAYMENT_MODE": "testnet",
            "AUTONOMERCE_PAYMENT_ALLOWED_CHAINS": "ARC-TESTNET",
            "AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS": PAYER,
            "AUTONOMERCE_PAYMENT_ALLOWED_PAYEE_WALLETS": PAYEE,
            "AUTONOMERCE_PAYMENT_SQLITE_PATH": str(
                tmp_path / "canonical-payments.sqlite3"
            ),
            "AUTONOMERCE_CIRCLE_CLI_BINARY": str(executable),
            "AUTONOMERCE_CIRCLE_CLI_SHA256": hashlib.sha256(
                executable.read_bytes()
            ).hexdigest(),
        },
        transaction_lookup=lambda _: None,
    )

    assert adapter.mode is PaymentMode.TESTNET
    assert adapter.allowed_chains == ("ARC-TESTNET",)
    assert adapter.allowed_payer_wallets == (PAYER,)
    assert adapter.allowed_payee_wallets == (PAYEE,)
    assert adapter.durability is StoreDurability.SINGLE_NODE


def test_circle_cli_rehashes_binary_immediately_before_transfer(tmp_path):
    executable = tmp_path / "circle"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    expected_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    executor = CircleCLIExecutor(
        mode=PaymentMode.TESTNET,
        binary=str(executable),
        binary_sha256=expected_sha256,
    )

    executable.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    executable.chmod(0o700)

    with pytest.raises(
        PaymentValidationError,
        match="SHA-256 does not match the pinned value",
    ):
        executor.execute(intent())


@pytest.mark.parametrize(
    "environment",
    [
        {
            "AUTONOMERCE_MODE": "live",
            "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
        },
        {"AUTONOMERCE_PAYMENT_MODE": "testnet"},
        {
            "AUTONOMERCE_MODE": "live",
            "AUTONOMERCE_CIRCLE_NETWORK": "BASE",
        },
    ],
)
def test_incomplete_live_environment_fails_instead_of_falling_back(environment):
    with pytest.raises(PaymentValidationError):
        build_payment_adapter(environment)


def test_payment_replay_cannot_change_private_receipt_publication():
    adapter = build_payment_adapter({})
    first = adapter.execute_payment(
        proposal(),
        idempotency_key="private-replay-1",
        chain="ARC-TESTNET",
        token="USDC",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        public=False,
    )
    replay = adapter.execute_payment(
        proposal(),
        idempotency_key="private-replay-1",
        chain="ARC-TESTNET",
        token="USDC",
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        public=True,
    )
    assert first.receipt.public is False
    assert replay.receipt.public is False
    assert len(adapter.executor.calls) == 1


def test_verification_hook_failure_leaves_ambiguous_payment_blocked():
    store = InMemoryPaymentStore()
    executor = OfflineCircleExecutor(clock=lambda: FIXED_TIME)
    processor = PaymentProcessor(
        policy=policy(),
        store=store,
        executor=executor,
        verification_hooks=(lambda receipt, payment_intent, result: False,),
    )
    with pytest.raises(ReceiptVerificationError):
        processor.pay(intent())
    assert store.get("idem-1").state is PaymentState.SUBMITTING
    assert processor.pay(intent()).state is PaymentState.SUBMITTING
    assert len(executor.calls) == 1


@pytest.mark.parametrize("failure_kind", ["rejection", "timeout"])
def test_ambiguous_circle_failures_are_durably_reconcilable_and_not_retried(
    tmp_path, failure_kind
):
    calls = []

    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        if failure_kind == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(
            argv,
            2,
            "",
            "transfer rejected; settlement status unknown",
        )

    database = tmp_path / f"{failure_kind}.sqlite3"
    executor = CircleCLIExecutor(
        mode=PaymentMode.TESTNET,
        runner=fake_runner,
    )
    processor = PaymentProcessor(
        policy=policy(mode=PaymentMode.TESTNET),
        store=SQLitePaymentStore(database),
        executor=executor,
    )
    with pytest.raises(CircleExecutionError) as failure:
        processor.pay(intent())
    assert failure.value.reconciliation_required

    reopened = SQLitePaymentStore(database)
    reconciliation = reopened.get_reconciliation("idem-1")
    assert reconciliation is not None
    assert reconciliation.reason_code == (
        "circle_cli_timeout"
        if failure_kind == "timeout"
        else "circle_cli_rejection_ambiguous"
    )
    replay = PaymentProcessor(
        policy=policy(mode=PaymentMode.TESTNET),
        store=reopened,
        executor=executor,
    ).pay(intent())
    assert replay.state is PaymentState.SUBMITTING
    assert len(calls) == 1


def test_terminal_mock_failure_is_not_retried():
    store = InMemoryPaymentStore()
    payment_intent = intent()
    executor = OfflineCircleExecutor(
        clock=lambda: FIXED_TIME,
        fail_payment_ids=(payment_intent.payment_id,),
    )
    processor = PaymentProcessor(policy=policy(), store=store, executor=executor)
    with pytest.raises(CircleExecutionError):
        processor.pay(payment_intent)
    assert store.get("idem-1").state is PaymentState.FAILED_TERMINAL
    assert processor.pay(payment_intent).state is PaymentState.FAILED_TERMINAL
    assert len(executor.calls) == 1


def test_circle_cli_adapter_uses_argv_no_shell_and_validates_response():
    calls = []

    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        payload = {
            "data": {
                "id": "circle-transfer-1",
                "state": "CONFIRMED",
                "blockchain": "ARC-TESTNET",
                "amounts": ["1"],
                "sourceAddress": PAYER,
                "destinationAddress": PAYEE,
                "txHash": TX_HASH,
                "updateDate": "2026-07-31T12:00:00Z",
            }
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    executor = CircleCLIExecutor(
        mode=PaymentMode.TESTNET,
        runner=fake_runner,
        clock=lambda: FIXED_TIME,
    )
    result = executor.execute(intent(key="idem;echo-unsafe"))

    argv, kwargs = calls[0]
    assert isinstance(argv, list)
    assert argv == [
        "circle",
        "wallet",
        "transfer",
        PAYEE,
        "--amount",
        "1",
        "--address",
        PAYER,
        "--chain",
        "ARC-TESTNET",
        "--output",
        "json",
    ]
    assert kwargs["shell"] is False
    assert kwargs["check"] is False
    assert result.transaction_hash == TX_HASH
    assert not result.simulated


def test_circle_cli_adapter_rejects_mismatched_confirmation():
    def fake_runner(argv, **kwargs):
        payload = {
            "data": {
                "state": "CONFIRMED",
                "blockchain": "ARC-TESTNET",
                "amounts": ["1"],
                "sourceAddress": PAYER,
                "destinationAddress": OTHER_PAYEE,
                "txHash": TX_HASH,
            }
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    executor = CircleCLIExecutor(mode=PaymentMode.TESTNET, runner=fake_runner)
    with pytest.raises(CircleExecutionError, match="unexpected payee"):
        executor.execute(intent())


def test_circle_cli_rejects_explicit_non_usdc_asset_descriptors():
    def fake_runner(argv, **kwargs):
        payload = {
            "data": {
                "state": "CONFIRMED",
                "blockchain": "ARC-TESTNET",
                "amounts": ["1"],
                "sourceAddress": PAYER,
                "destinationAddress": PAYEE,
                "txHash": TX_HASH,
                "token": "NOT-USDC",
                "asset": OTHER_PAYEE,
            }
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    executor = CircleCLIExecutor(
        mode=PaymentMode.TESTNET,
        runner=fake_runner,
    )
    with pytest.raises(
        CircleExecutionError,
        match="unexpected token|unexpected asset",
    ):
        executor.execute(intent())


def _x402_header(payload: dict) -> str:
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return base64.b64encode(encoded).decode()


def test_x402_payment_requirement_parser_handles_v2_atomic_usdc():
    requirement = parse_x402_payment_requirement(
        {
            "PAYMENT-REQUIRED": _x402_header(
                {
                    "x402Version": 2,
                    "resource": {
                        "url": "https://seller.example/paid/verify",
                        "description": "Verify one claim",
                    },
                    "accepts": [
                        {
                            "scheme": "exact",
                            "network": "eip155:84532",
                            "amount": "400000",
                            "asset": BASE_SEPOLIA_USDC,
                            "payTo": PAYEE,
                            "maxTimeoutSeconds": 60,
                            "extra": {
                                "paymentIdentifier": "x402-order-1",
                            },
                        }
                    ],
                }
            )
        }
    )
    assert requirement.x402_version == 2
    assert requirement.chain == "BASE-SEPOLIA"
    assert requirement.amount_usdc == Decimal("0.4")
    assert requirement.token == "USDC"
    assert requirement.requirement_id == "x402-order-1"

    payment_intent = requirement.to_intent(
        proposal(price="0.4"),
        idempotency_key="idem-x402-order-1",
        payer_wallet=PAYER,
        expected_chain="BASE-SEPOLIA",
        expected_token="USDC",
        expected_asset=BASE_SEPOLIA_USDC,
        expected_payee_wallet=PAYEE,
        expected_resource_url="https://seller.example/paid/verify",
        expected_requirement_id="x402-order-1",
    )
    assert payment_intent.x402_requirement_fingerprint == requirement.fingerprint
    decision = PaymentPolicyGate().evaluate(
        payment_intent,
        policy(
            mode=PaymentMode.TESTNET,
            chains=("BASE-SEPOLIA",),
            assets={"BASE-SEPOLIA": (BASE_SEPOLIA_USDC,)},
        ),
    )
    assert decision.authorized


def test_x402_to_intent_requires_exact_complete_binding():
    requirement = parse_x402_payment_requirement(
        {
            "x402Version": 2,
            "resource": {"url": "https://seller.example/paid/verify"},
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "BASE-SEPOLIA",
                    "amount": "400000",
                    "asset": BASE_SEPOLIA_USDC,
                    "token": "USDC",
                    "payTo": PAYEE,
                    "extra": {"paymentIdentifier": "x402-order-1"},
                }
            ],
        }
    )
    binding = {
        "expected_chain": "BASE-SEPOLIA",
        "expected_token": "USDC",
        "expected_asset": BASE_SEPOLIA_USDC,
        "expected_payee_wallet": PAYEE,
        "expected_resource_url": "https://seller.example/paid/verify",
        "expected_requirement_id": "x402-order-1",
    }
    with pytest.raises(PaymentValidationError, match="amount"):
        requirement.to_intent(
            proposal(price="0.5"),
            idempotency_key="idem-x402-order-1",
            payer_wallet=PAYER,
            **binding,
        )

    mismatches = {
        "expected_chain": "BASE",
        "expected_token": "EURC",
        "expected_asset": BASE_USDC,
        "expected_payee_wallet": OTHER_PAYEE,
        "expected_resource_url": "https://seller.example/paid/other",
        "expected_requirement_id": "x402-order-2",
    }
    for field_name, bad_value in mismatches.items():
        bad_binding = {**binding, field_name: bad_value}
        with pytest.raises(PaymentValidationError):
            requirement.to_intent(
                proposal(price="0.4"),
                idempotency_key=f"idem-{field_name}",
                payer_wallet=PAYER,
                **bad_binding,
            )


def test_x402_rejects_conflicting_aliases_and_binds_full_fingerprint():
    with pytest.raises(X402ParseError, match="identifier"):
        parse_x402_payment_requirement(
            {
                "x402Version": 2,
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "BASE-SEPOLIA",
                        "amount": "400000",
                        "amountUsdc": "0.4",
                        "asset": BASE_SEPOLIA_USDC,
                        "payTo": PAYEE,
                        "paymentIdentifier": "one",
                        "extra": {"idempotencyKey": "two"},
                    }
                ],
            }
        )

    def requirement_with_nonce(nonce):
        return parse_x402_payment_requirement(
            {
                "x402Version": 2,
                "resource": {"url": "https://seller.example/paid/verify"},
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "BASE-SEPOLIA",
                        "amount": "400000",
                        "asset": BASE_SEPOLIA_USDC,
                        "payTo": PAYEE,
                        "maxTimeoutSeconds": 60,
                        "extra": {
                            "paymentIdentifier": "x402-order-1",
                            "nonce": nonce,
                        },
                    }
                ],
            }
        )

    first = requirement_with_nonce("one")
    second = requirement_with_nonce("two")
    assert first.fingerprint != second.fingerprint
    common = {
        "idempotency_key": "idem-x402-order-1",
        "payer_wallet": PAYER,
        "expected_chain": "BASE-SEPOLIA",
        "expected_token": "USDC",
        "expected_asset": BASE_SEPOLIA_USDC,
        "expected_payee_wallet": PAYEE,
        "expected_resource_url": "https://seller.example/paid/verify",
        "expected_requirement_id": "x402-order-1",
    }
    assert (
        first.to_intent(proposal(price="0.4"), **common).fingerprint
        != second.to_intent(proposal(price="0.4"), **common).fingerprint
    )


@pytest.mark.parametrize(
    "header",
    [
        "not-base64!",
        _x402_header({"x402Version": 99, "accepts": []}),
        _x402_header(
            {
                "x402Version": 2,
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "amount": "1.5",
                        "asset": BASE_USDC,
                        "payTo": PAYEE,
                    }
                ],
            }
        ),
    ],
)
def test_x402_parser_rejects_malformed_or_unsafe_requirements(header):
    with pytest.raises(X402ParseError):
        parse_x402_payment_requirement(header)


def test_receipt_verification_lookup_hook_and_redaction():
    payment_intent = intent()
    executor = OfflineCircleExecutor(clock=lambda: FIXED_TIME)
    execution = executor.execute(payment_intent)
    receipt = PaymentReceipt(
        payment_id=payment_intent.payment_id,
        proposal_id=payment_intent.proposal_id,
        idempotency_key=payment_intent.idempotency_key,
        state=PaymentState.CONFIRMED,
        amount_usdc=payment_intent.amount_usdc,
        chain=payment_intent.chain,
        payer_wallet=payment_intent.payer_wallet,
        payee_wallet=payment_intent.payee_wallet,
        transaction_hash=execution.transaction_hash,
        confirmed_at=execution.confirmed_at,
        public=True,
    )
    verdict = verify_receipt(
        receipt,
        payment_intent,
        execution,
        mode=PaymentMode.OFFLINE,
        hooks=(lambda receipt, payment_intent, result: True,),
    )
    assert verdict.verified

    redacted = public_payment_receipt(
        receipt,
        mode=PaymentMode.OFFLINE,
        verified=True,
        metadata={
            "token": "USDC",
            "Authorization": "Bearer do-not-leak",  # secret-scan: allow-test-fixture
            "nested": {"accessToken": "circle-session"},
        },
    )
    assert redacted["metadata"]["token"] == "USDC"
    assert redacted["metadata"]["Authorization"] == "[REDACTED]"
    assert redacted["metadata"]["nested"]["accessToken"] == "[REDACTED]"
    assert "idempotencyKey" not in redacted
    assert redacted["settlementKind"] == "simulated"

    headers = redact_headers(
        {"authorization": "Bearer secret-value", "content-type": "application/json"}  # secret-scan: allow-test-fixture
    )
    assert headers["authorization"] == "[REDACTED]"
    assert headers["content-type"] == "application/json"


def test_live_receipt_requires_independent_asset_bound_lookup():
    payment_intent = intent(
        chain="BASE-SEPOLIA",
        asset=BASE_SEPOLIA_USDC,
    )
    execution = ExecutionResult(
        state="CONFIRMED",
        amount_usdc=payment_intent.amount_usdc,
        chain=payment_intent.chain,
        payer_wallet=payment_intent.payer_wallet,
        payee_wallet=payment_intent.payee_wallet,
        transaction_hash=TX_HASH,
        confirmed_at="2026-07-31T12:00:00Z",
        token=payment_intent.token,
        asset=payment_intent.asset,
    )
    receipt = PaymentReceipt(
        payment_id=payment_intent.payment_id,
        proposal_id=payment_intent.proposal_id,
        idempotency_key=payment_intent.idempotency_key,
        state=PaymentState.CONFIRMED,
        amount_usdc=payment_intent.amount_usdc,
        chain=payment_intent.chain,
        payer_wallet=payment_intent.payer_wallet,
        payee_wallet=payment_intent.payee_wallet,
        transaction_hash=TX_HASH,
        confirmed_at=execution.confirmed_at,
        token=payment_intent.token,
        asset=payment_intent.asset,
    )

    unmarked = verify_receipt(
        receipt,
        payment_intent,
        execution,
        mode=PaymentMode.TESTNET,
        hooks=(lambda *_: True,),
    )
    assert not unmarked.verified
    assert unmarked.reason_code == "independent_lookup_required"

    lookup = transaction_lookup_hook(
        lambda transaction_hash: {
            "confirmed": True,
            "chain": payment_intent.chain,
            "amountUsdc": str(payment_intent.amount_usdc),
            "payerWallet": payment_intent.payer_wallet,
            "payeeWallet": payment_intent.payee_wallet,
            "transactionHash": transaction_hash,
            "token": payment_intent.token,
            "asset": payment_intent.asset,
        }
    )
    verified = verify_receipt(
        receipt,
        payment_intent,
        execution,
        mode=PaymentMode.TESTNET,
        hooks=(lookup,),
    )
    assert verified.verified

    wrong_asset_lookup = transaction_lookup_hook(
        lambda transaction_hash: {
            "confirmed": True,
            "chain": payment_intent.chain,
            "amountUsdc": str(payment_intent.amount_usdc),
            "payerWallet": payment_intent.payer_wallet,
            "payeeWallet": payment_intent.payee_wallet,
            "transactionHash": transaction_hash,
            "token": payment_intent.token,
            "asset": OTHER_PAYEE,
        }
    )
    rejected = verify_receipt(
        receipt,
        payment_intent,
        execution,
        mode=PaymentMode.TESTNET,
        hooks=(wrong_asset_lookup,),
    )
    assert not rejected.verified
    assert rejected.reason_code == "lookup_mismatch"


def test_tampered_receipt_fails_verification():
    payment_intent = intent()
    execution = OfflineCircleExecutor(clock=lambda: FIXED_TIME).execute(payment_intent)
    receipt = PaymentReceipt(
        payment_id=payment_intent.payment_id,
        proposal_id=payment_intent.proposal_id,
        idempotency_key=payment_intent.idempotency_key,
        state=PaymentState.CONFIRMED,
        amount_usdc=payment_intent.amount_usdc,
        chain=payment_intent.chain,
        payer_wallet=payment_intent.payer_wallet,
        payee_wallet=payment_intent.payee_wallet,
        transaction_hash=execution.transaction_hash,
    )
    tampered = replace(receipt, payee_wallet=OTHER_PAYEE)
    verdict = verify_receipt(
        tampered,
        payment_intent,
        execution,
        mode=PaymentMode.OFFLINE,
    )
    assert not verdict.verified
    assert verdict.reason_code == "payee_mismatch"
