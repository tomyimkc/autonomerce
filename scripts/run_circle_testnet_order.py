#!/usr/bin/env python3
"""Run one bounded OfferRail order on Arc testnet, or preflight without transfer.

The default operational path is fail-closed: the caller must choose ``--dry-run``
or provide the exact transfer confirmation phrase.  This script never performs
Circle authentication and never supports mainnet.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for package_root in (PROJECT_ROOT / "apps" / "api", PROJECT_ROOT / "packages"):
    package_text = str(package_root)
    if package_text not in sys.path:
        sys.path.insert(0, package_text)

from autonomerce.contracts import (  # noqa: E402
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    PaymentReceipt,
    Proposal,
    ProposalState,
    stable_id,
    usdc_text,
)
from autonomerce.payments import (  # noqa: E402
    ARC_TESTNET_EXPLORER_URL,
    ARC_TESTNET_USDC,
    CircleCLIExecutor,
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    PaymentPolicyGate,
    PaymentProcessor,
    SQLitePaymentStore,
    arc_testnet_transaction_lookup_factory,
    transaction_lookup_hook,
)
from offerrail import (  # noqa: E402
    PolicyContext,
    capability_to_sku,
    create_proposal,
    make_idempotency_key,
    transition_proposal,
)


TRANSFER_CONFIRMATION = "EXECUTE_ONE_ARC_TESTNET_USDC_TRANSFER"
CHAIN = "ARC-TESTNET"
TOKEN = "USDC"
AMOUNT_USDC = Decimal("0.10")
MAXIMUM_TOTAL_USDC = Decimal("0.20")
MAXIMUM_PAYMENT_COUNT = 2


ExecutorFactory = Callable[..., Any]
LookupFactory = Callable[[], Callable[[str], Mapping[str, Any] | None]]


@dataclass(frozen=True)
class RunConfiguration:
    order_id: str
    payer_wallet: str
    payee_wallet: str
    circle_cli_binary: Path
    circle_cli_sha256: str
    sqlite_path: Path
    evidence_path: Path
    circle_cli_interpreter: Path | None = None
    circle_cli_interpreter_sha256: str | None = None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _accepted_offerrail_proposal(order_id: str) -> Proposal:
    capability = CapabilityDescriptor(
        capability_id="arc_testnet_order_proof",
        name="Arc testnet order-bound settlement proof",
        description=(
            "Return an independently verified Arc testnet USDC settlement receipt"
        ),
        input_schema={
            "type": "object",
            "required": ["orderId"],
            "properties": {"orderId": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["transactionHash", "receiptVerified"],
        },
        tags=("offerrail", "circle", "arc-testnet"),
    )
    sku = capability_to_sku(
        capability,
        base_price_usdc=AMOUNT_USDC,
        acceptance_criteria=(
            "Arc testnet receipt status is successful",
            "canonical USDC Transfer log independently matches the order",
        ),
        maximum_latency_seconds=300,
        capacity_per_hour=2,
    )
    buyer_url = "https://buyer.testnet.invalid/agent"
    policy = CommercialPolicy(
        policy_id="offerrail_arc_testnet_proof_v1",
        owner_id="owner_arc_testnet_proof",
        minimum_price_usdc=AMOUNT_USDC,
        maximum_price_usdc=AMOUNT_USDC,
        maximum_discount_fraction=Decimal("0"),
        maximum_open_proposals=2,
        maximum_tasks_per_hour=2,
        allowed_buyer_hosts=("buyer.testnet.invalid",),
        blocked_buyer_hosts=(),
        allowed_chains=(CHAIN,),
        allowed_token=TOKEN,
        unattended=True,
    )
    buyer_need = BuyerNeed(
        need_id=stable_id("need", "arc-testnet-proof", order_id),
        buyer_agent_url=buyer_url,
        desired_outcome=capability.description,
        maximum_price_usdc=AMOUNT_USDC,
        input_payload={"orderId": order_id},
    )
    draft = create_proposal(
        sku=sku,
        policy=policy,
        seller_agent_url="https://seller.testnet.invalid/agent",
        buyer_need=buyer_need,
        problem_observed=f"Order {order_id} requires testnet settlement proof",
        context=PolicyContext(
            chain=CHAIN,
            token=TOKEN,
            reserving_new_proposal=True,
        ),
    )
    offered = transition_proposal(
        draft,
        ProposalState.OFFERED,
        expected_revision=draft.revision,
    )
    return transition_proposal(
        offered,
        ProposalState.ACCEPTED,
        expected_revision=offered.revision,
    )


def _payment_intent(
    proposal: Proposal,
    *,
    order_id: str,
    payer_wallet: str,
    payee_wallet: str,
) -> PaymentIntent:
    idempotency_key = make_idempotency_key(
        "circle-arc-testnet-order",
        order_id,
        proposal.proposal_id,
        usdc_text(proposal.price_usdc),
        CHAIN,
        TOKEN,
        payer_wallet.lower(),
        payee_wallet.lower(),
    )
    return PaymentIntent.from_proposal(
        proposal,
        idempotency_key=idempotency_key,
        chain=CHAIN,
        token=TOKEN,
        asset=ARC_TESTNET_USDC,
        payer_wallet=payer_wallet,
        payee_wallet=payee_wallet,
        metadata={"orderId": order_id},
    )


def _payment_policy(intent: PaymentIntent) -> PaymentPolicy:
    return PaymentPolicy(
        policy_id="circle_arc_testnet_order_cap_v1",
        mode=PaymentMode.TESTNET,
        maximum_per_payment_usdc=AMOUNT_USDC,
        maximum_total_usdc=MAXIMUM_TOTAL_USDC,
        maximum_payment_count=MAXIMUM_PAYMENT_COUNT,
        allowed_chains=(CHAIN,),
        allowed_token=TOKEN,
        allowed_payer_wallets=(intent.payer_wallet,),
        allowed_payee_wallets=(intent.payee_wallet,),
        allowed_assets_by_chain={CHAIN: (ARC_TESTNET_USDC,)},
        allowed_schemes=("exact",),
        require_payer_allowlist=True,
        require_payee_allowlist=True,
        allow_self_payment=False,
        mainnet_enabled=False,
        enabled=True,
    )


def _build_executor(
    config: RunConfiguration,
    *,
    executor_factory: ExecutorFactory,
) -> Any:
    kwargs: dict[str, Any] = {
        "mode": PaymentMode.TESTNET,
        "binary": str(config.circle_cli_binary),
        "binary_sha256": config.circle_cli_sha256,
        "working_directory": "/",
    }
    if config.circle_cli_interpreter is not None:
        kwargs["interpreter_binary"] = str(config.circle_cli_interpreter)
    if config.circle_cli_interpreter_sha256 is not None:
        kwargs["interpreter_sha256"] = config.circle_cli_interpreter_sha256
    return executor_factory(
        **kwargs,
    )


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            # os.replace() normally consumed the temporary path.
            pass


def _testnet_evidence(
    *,
    config: RunConfiguration,
    proposal: Proposal,
    receipt: PaymentReceipt,
    replay: PaymentReceipt,
) -> dict[str, Any]:
    transaction_hash = receipt.transaction_hash
    if not transaction_hash or replay.transaction_hash != transaction_hash:
        raise RuntimeError("idempotent replay did not preserve the transaction hash")
    return {
        "schemaVersion": "autonomerce.transaction.public.v1",
        "recordKind": "transaction",
        "synthetic": False,
        "evidenceClassification": "testnet",
        "orderId": stable_id("order", config.order_id),
        "proposalId": proposal.proposal_id,
        "paymentId": receipt.payment_id,
        "fulfillmentId": None,
        "network": CHAIN,
        "token": TOKEN,
        "amountUsdc": usdc_text(receipt.amount_usdc),
        "movesFunds": True,
        "transactionHash": transaction_hash,
        "explorerUrl": f"{ARC_TESTNET_EXPLORER_URL}/tx/{transaction_hash}",
        # This runner-generated redacted record omits wallets and the internal
        # idempotency key. Separate owner-approved publication may add wallet fields.
        "payerWallet": None,
        "payeeWallet": None,
        "confirmedAt": receipt.confirmed_at,
        "externalCustomer": False,
        "customerRelationship": "unknown",
        "countedAsRevenue": False,
        "delivered": False,
        "acceptanceVerdict": "pending",
        "customerConsentToPublish": False,
        "consentRecordId": None,
        "artifactHash": None,
        "repositoryCommit": None,
        "deployedRevision": None,
        "evidenceGeneratedAt": _utc_timestamp(),
        "notes": [
            "Arc testnet proof only; countedAsRevenue=false.",
            "Payer, payee, Circle credentials, and idempotency key are redacted.",
            "The same order-bound idempotency key was replayed without a second execution.",
        ],
    }


def run_order(
    config: RunConfiguration,
    *,
    dry_run: bool,
    confirmation: str | None,
    executor_factory: ExecutorFactory = CircleCLIExecutor,
    lookup_factory: LookupFactory = arc_testnet_transaction_lookup_factory,
) -> dict[str, Any]:
    if dry_run:
        if confirmation is not None:
            raise ValueError("dry-run mode cannot include a transfer confirmation")
    elif confirmation != TRANSFER_CONFIRMATION:
        raise ValueError("exact Arc testnet transfer confirmation is required")

    order_id = str(config.order_id).strip()
    if not order_id or len(order_id) > 160:
        raise ValueError("order_id must contain 1 to 160 characters")
    if config.sqlite_path == config.evidence_path:
        raise ValueError("SQLite and evidence paths must be different")

    proposal = _accepted_offerrail_proposal(order_id)
    if proposal.state is not ProposalState.ACCEPTED:
        raise RuntimeError("OfferRail proposal did not reach accepted state")
    intent = _payment_intent(
        proposal,
        order_id=order_id,
        payer_wallet=config.payer_wallet,
        payee_wallet=config.payee_wallet,
    )
    policy = _payment_policy(intent)
    store = SQLitePaymentStore(config.sqlite_path)
    executor = _build_executor(config, executor_factory=executor_factory)
    # Validates the exact transfer command without executing it.
    executor.build_argv(intent)
    lookup = lookup_factory()
    hook = transaction_lookup_hook(lookup)

    if dry_run:
        existing = store.get(intent.idempotency_key)
        if existing is None:
            decision = PaymentPolicyGate().evaluate(
                intent,
                policy,
                store.snapshot(policy.policy_id),
            )
            authorized = decision.authorized
            reason_code = decision.reason_code
        else:
            authorized = True
            reason_code = "idempotent_replay_available"
        return {
            "mode": "dry-run",
            "transferExecuted": False,
            "transferAuthorized": False,
            "policyWouldAuthorize": authorized,
            "policyReasonCode": reason_code,
            "proposalState": proposal.state.value,
            "network": CHAIN,
            "token": TOKEN,
            "asset": ARC_TESTNET_USDC,
            "amountUsdc": usdc_text(intent.amount_usdc),
            "maximumPerPaymentUsdc": usdc_text(
                policy.maximum_per_payment_usdc
            ),
            "maximumTotalUsdc": usdc_text(policy.maximum_total_usdc),
            "maximumPaymentCount": policy.maximum_payment_count,
            "durableStore": str(config.sqlite_path),
            "interpreterPinned": config.circle_cli_interpreter is not None,
            "evidenceWritten": False,
            "countedAsRevenue": False,
        }

    processor = PaymentProcessor(
        policy=policy,
        store=store,
        executor=executor,
        verification_hooks=(hook,),
    )
    receipt = processor.pay(intent)
    replay = processor.pay(intent)
    if receipt != replay:
        raise RuntimeError("idempotent replay returned different payment evidence")
    evidence = _testnet_evidence(
        config=config,
        proposal=proposal,
        receipt=receipt,
        replay=replay,
    )
    _write_private_json(config.evidence_path, evidence)
    return {
        "mode": "testnet-transfer",
        "transferExecuted": True,
        "proposalId": proposal.proposal_id,
        "paymentId": receipt.payment_id,
        "transactionHash": receipt.transaction_hash,
        "explorerUrl": evidence["explorerUrl"],
        "idempotentReplayVerified": True,
        "evidencePath": str(config.evidence_path),
        "countedAsRevenue": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight or execute one 0.10 USDC OfferRail order on Arc testnet."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="validate proposal, policy, durable store, pinned CLI, and lookup wiring",
    )
    mode.add_argument(
        "--confirm-testnet-transfer",
        metavar="PHRASE",
        help=f"must equal exactly: {TRANSFER_CONFIRMATION}",
    )
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--payer-wallet", required=True)
    parser.add_argument("--payee-wallet", required=True)
    parser.add_argument(
        "--circle-cli-binary",
        required=True,
        type=Path,
        help="absolute path to the pinned Circle CLI executable",
    )
    parser.add_argument(
        "--circle-cli-sha256",
        required=True,
        help="expected lowercase SHA-256 of the Circle CLI executable",
    )
    parser.add_argument(
        "--circle-cli-interpreter",
        type=Path,
        help="optional absolute interpreter used to launch the Circle CLI script",
    )
    parser.add_argument(
        "--circle-cli-interpreter-sha256",
        help="required SHA-256 when --circle-cli-interpreter is provided",
    )
    parser.add_argument("--sqlite-path", required=True, type=Path)
    parser.add_argument("--evidence-path", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if (
        args.confirm_testnet_transfer is not None
        and args.confirm_testnet_transfer != TRANSFER_CONFIRMATION
    ):
        parser.error(
            "--confirm-testnet-transfer did not match the exact required phrase"
        )
    if (args.circle_cli_interpreter is None) != (
        args.circle_cli_interpreter_sha256 is None
    ):
        parser.error(
            "--circle-cli-interpreter and "
            "--circle-cli-interpreter-sha256 must be provided together"
        )
    config = RunConfiguration(
        order_id=args.order_id,
        payer_wallet=args.payer_wallet,
        payee_wallet=args.payee_wallet,
        circle_cli_binary=args.circle_cli_binary,
        circle_cli_sha256=args.circle_cli_sha256,
        sqlite_path=args.sqlite_path,
        evidence_path=args.evidence_path,
        circle_cli_interpreter=args.circle_cli_interpreter,
        circle_cli_interpreter_sha256=args.circle_cli_interpreter_sha256,
    )
    result = run_order(
        config,
        dry_run=bool(args.dry_run),
        confirmation=args.confirm_testnet_transfer,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
