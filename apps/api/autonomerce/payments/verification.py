"""Independent receipt verification hooks."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Mapping, Optional, Protocol

from autonomerce.contracts import PaymentReceipt, PaymentState, usdc

from .models import (
    ExecutionResult,
    PaymentIntent,
    PaymentMode,
    ReceiptVerification,
    canonical_chain,
    normalize_asset_contract,
    normalize_token,
    normalize_transaction_hash,
    normalize_wallet_address,
)

_INDEPENDENT_LOOKUP_MARKER = "_autonomerce_independent_transaction_lookup"


class ReceiptHook(Protocol):
    def __call__(
        self,
        receipt: PaymentReceipt,
        intent: PaymentIntent,
        execution: ExecutionResult,
    ) -> bool | ReceiptVerification | None: ...


def has_independent_transaction_lookup(hooks: Iterable[ReceiptHook]) -> bool:
    return any(bool(getattr(hook, _INDEPENDENT_LOOKUP_MARKER, False)) for hook in hooks)


def verify_receipt(
    receipt: PaymentReceipt,
    intent: PaymentIntent,
    execution: ExecutionResult,
    *,
    mode: PaymentMode | str,
    hooks: Iterable[ReceiptHook] = (),
) -> ReceiptVerification:
    """Verify executor evidence against the policy-authorized intent.

    Hooks fail closed: False, an unverified result, or any exception denies the
    receipt. A hook returning None means it completed without an additional verdict.
    """

    normalized_mode = PaymentMode.parse(mode)

    def fail(reason: str, explanation: str) -> ReceiptVerification:
        return ReceiptVerification(False, reason, explanation)

    if receipt.state is not PaymentState.CONFIRMED:
        return fail("receipt_not_confirmed", "receipt state is not confirmed")
    if execution.state != "CONFIRMED":
        return fail("execution_not_confirmed", "executor did not report confirmation")
    if receipt.payment_id != intent.payment_id:
        return fail("payment_id_mismatch", "receipt payment ID does not match intent")
    if receipt.proposal_id != intent.proposal_id:
        return fail("proposal_id_mismatch", "receipt proposal ID does not match intent")
    if receipt.idempotency_key != intent.idempotency_key:
        return fail("idempotency_mismatch", "receipt idempotency key does not match")
    if (
        receipt.amount_usdc != intent.amount_usdc
        or execution.amount_usdc != intent.amount_usdc
    ):
        return fail("amount_mismatch", "receipt amount does not match intent")
    if canonical_chain(receipt.chain) != intent.chain or execution.chain != intent.chain:
        return fail("chain_mismatch", "receipt chain does not match intent")
    if (
        receipt.token != intent.token
        or execution.token != intent.token
    ):
        return fail("token_mismatch", "receipt token does not match intent")
    if execution.asset != intent.asset:
        return fail("asset_mismatch", "receipt asset does not match intent")
    if normalized_mode.is_live and receipt.asset != intent.asset:
        return fail("asset_mismatch", "receipt asset does not match intent")
    if (
        normalized_mode is PaymentMode.OFFLINE
        and receipt.asset not in {None, intent.asset}
    ):
        return fail("asset_mismatch", "receipt asset does not match intent")
    try:
        receipt_payer = normalize_wallet_address(receipt.payer_wallet, receipt.chain)
        receipt_payee = normalize_wallet_address(receipt.payee_wallet, receipt.chain)
    except Exception:
        return fail("invalid_receipt_wallet", "receipt contains an invalid wallet address")
    if (
        receipt_payer.lower() != intent.payer_wallet.lower()
        or execution.payer_wallet.lower() != intent.payer_wallet.lower()
    ):
        return fail("payer_mismatch", "receipt payer does not match intent")
    if (
        receipt_payee.lower() != intent.payee_wallet.lower()
        or execution.payee_wallet.lower() != intent.payee_wallet.lower()
    ):
        return fail("payee_mismatch", "receipt payee does not match intent")
    try:
        receipt_hash = normalize_transaction_hash(receipt.transaction_hash or "")
    except Exception:
        return fail("invalid_transaction_hash", "receipt transaction hash is invalid")
    if receipt_hash.lower() != (execution.transaction_hash or "").lower():
        return fail(
            "transaction_hash_mismatch",
            "receipt transaction hash does not match executor evidence",
        )
    if normalized_mode is PaymentMode.OFFLINE and not execution.simulated:
        return fail("offline_evidence_mismatch", "offline mode requires simulated evidence")
    if normalized_mode.is_live and execution.simulated:
        return fail("live_evidence_mismatch", "live modes reject simulated evidence")

    configured_hooks = tuple(hooks)
    if normalized_mode.is_live:
        if intent.asset is None or intent.asset == intent.token:
            return fail(
                "canonical_asset_required",
                "live payment intent lacks a canonical USDC contract binding",
            )
        if not has_independent_transaction_lookup(configured_hooks):
            return fail(
                "independent_lookup_required",
                "live confirmation requires an independent transaction lookup hook",
            )

    hook_results: list[str] = []
    for index, hook in enumerate(configured_hooks):
        name = getattr(hook, "__name__", hook.__class__.__name__)
        try:
            result = hook(receipt, intent, execution)
        except Exception:
            return fail(
                "verification_hook_error",
                f"receipt verification hook {name} raised an exception",
            )
        if isinstance(result, ReceiptVerification):
            if not result.verified:
                return result
            hook_results.append(result.reason_code)
        elif result is False:
            return fail(
                "verification_hook_denied",
                f"receipt verification hook {name} denied the receipt",
            )
        elif result is not True and result is not None:
            return fail(
                "verification_hook_invalid",
                f"receipt verification hook {index} returned an invalid result",
            )
        else:
            hook_results.append(name)
    return ReceiptVerification(
        True,
        "verified",
        "receipt matches the authorized intent and all verification hooks passed",
        tuple(hook_results),
    )


Lookup = Callable[[str], Optional[Mapping[str, Any]]]


def transaction_lookup_hook(lookup: Lookup) -> ReceiptHook:
    """Build a hook around an explorer/RPC/facilitator transaction lookup.

    The caller owns network I/O. The hook only verifies the returned evidence fields.
    Missing fields fail closed.
    """

    def verify(
        receipt: PaymentReceipt,
        intent: PaymentIntent,
        execution: ExecutionResult,
    ) -> ReceiptVerification:
        evidence = lookup(receipt.transaction_hash or "")
        if not isinstance(evidence, Mapping):
            return ReceiptVerification(
                False, "lookup_missing", "transaction lookup returned no evidence"
            )
        try:
            confirmed = evidence["confirmed"]
            if confirmed is not True:
                raise ValueError("transaction is not confirmed")
            chain = canonical_chain(str(evidence["chain"]))
            amount = usdc(evidence["amountUsdc"])
            payer = normalize_wallet_address(str(evidence["payerWallet"]), chain)
            payee = normalize_wallet_address(str(evidence["payeeWallet"]), chain)
            transaction_hash = normalize_transaction_hash(
                str(evidence["transactionHash"])
            )
            token = normalize_token(str(evidence["token"]))
            asset = normalize_asset_contract(
                str(evidence["asset"]),
                chain,
                token=token,
            )
        except (KeyError, TypeError, ValueError):
            return ReceiptVerification(
                False, "lookup_malformed", "transaction lookup evidence is malformed"
            )
        if (
            chain != intent.chain
            or amount != intent.amount_usdc
            or payer.lower() != intent.payer_wallet.lower()
            or payee.lower() != intent.payee_wallet.lower()
            or transaction_hash.lower()
            != (receipt.transaction_hash or "").lower()
            or token != intent.token
            or asset != intent.asset
        ):
            return ReceiptVerification(
                False,
                "lookup_mismatch",
                "transaction lookup does not match the authorized intent",
            )
        return ReceiptVerification(
            True, "lookup_verified", "transaction lookup matches the intent"
        )

    setattr(verify, _INDEPENDENT_LOOKUP_MARKER, True)
    return verify
