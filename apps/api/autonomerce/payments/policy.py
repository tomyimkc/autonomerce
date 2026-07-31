"""Deterministic, fail-closed authorization for autonomous USDC payments."""

from __future__ import annotations

from decimal import Decimal

from .models import (
    KNOWN_USDC_ASSETS,
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    PaymentPolicyDecision,
    SpendingSnapshot,
    is_mainnet_chain,
    is_testnet_chain,
    resource_host,
)


class PaymentPolicyGate:
    """Pure policy evaluation with stable denial reason codes."""

    def evaluate(
        self,
        intent: PaymentIntent,
        policy: PaymentPolicy,
        snapshot: SpendingSnapshot | None = None,
    ) -> PaymentPolicyDecision:
        current = snapshot or SpendingSnapshot()

        def deny(reason_code: str, explanation: str) -> PaymentPolicyDecision:
            return PaymentPolicyDecision(
                authorized=False,
                reason_code=reason_code,
                explanation=explanation,
                policy_id=policy.policy_id,
                payment_id=intent.payment_id,
            )

        if not policy.enabled:
            return deny("policy_disabled", "payment policy is disabled")
        if intent.proposal_state.value != "accepted":
            return deny("proposal_not_accepted", "proposal is not in accepted state")
        if intent.amount_usdc != intent.expected_amount_usdc:
            return deny(
                "proposal_amount_mismatch",
                "payment amount does not exactly match the accepted proposal",
            )
        if intent.amount_usdc <= Decimal("0"):
            return deny("invalid_amount", "payment amount must be greater than zero")
        if intent.amount_usdc > policy.maximum_per_payment_usdc:
            return deny("per_payment_limit", "payment exceeds the per-payment limit")
        if current.committed_payment_count >= policy.maximum_payment_count:
            return deny("payment_count_limit", "payment count limit is exhausted")
        if (
            current.committed_usdc + intent.amount_usdc
            > policy.maximum_total_usdc
        ):
            return deny("cumulative_limit", "payment exceeds the cumulative spend limit")
        if intent.chain not in policy.allowed_chains:
            return deny("chain_not_allowed", "payment chain is not allowed by policy")
        if policy.mode is PaymentMode.TESTNET and not is_testnet_chain(intent.chain):
            return deny("mode_chain_mismatch", "testnet mode requires a testnet chain")
        if policy.mode is PaymentMode.MAINNET:
            if not policy.mainnet_enabled:
                return deny(
                    "mainnet_not_enabled",
                    "mainnet payments require explicit owner policy opt-in",
                )
            if not is_mainnet_chain(intent.chain):
                return deny("mode_chain_mismatch", "mainnet mode requires a mainnet chain")
        if intent.token != policy.allowed_token:
            return deny("token_mismatch", "payment token does not match policy")
        if intent.scheme not in policy.allowed_schemes:
            return deny("scheme_not_allowed", "x402 payment scheme is not allowed")

        if intent.asset:
            if intent.asset.upper() == policy.allowed_token:
                allowed_assets = (intent.asset.lower(),)
            else:
                allowed_assets = policy.allowed_assets_by_chain.get(intent.chain)
                if allowed_assets is None:
                    allowed_assets = KNOWN_USDC_ASSETS.get(intent.chain)
            if not allowed_assets:
                return deny(
                    "asset_not_allowlisted",
                    "asset address is present but no trusted asset allowlist exists",
                )
            if intent.asset.lower() not in allowed_assets:
                return deny(
                    "asset_mismatch",
                    "x402 asset address does not match the policy token",
                )

        payer = intent.payer_wallet.lower()
        payee = intent.payee_wallet.lower()
        if policy.require_payer_allowlist and not policy.allowed_payer_wallets:
            return deny(
                "payer_allowlist_missing",
                "policy requires an explicit payer wallet allowlist",
            )
        if policy.allowed_payer_wallets and payer not in policy.allowed_payer_wallets:
            return deny("payer_not_allowed", "payer wallet is not allowed by policy")
        if policy.require_payee_allowlist and not policy.allowed_payee_wallets:
            return deny(
                "payee_allowlist_missing",
                "policy requires an explicit destination wallet allowlist",
            )
        if policy.allowed_payee_wallets and payee not in policy.allowed_payee_wallets:
            return deny("payee_not_allowed", "destination wallet is not allowed by policy")
        if payer == payee and not policy.allow_self_payment:
            return deny("self_payment", "self-payments are disabled by policy")
        if policy.require_x402_requirement_id and not intent.x402_requirement_id:
            return deny(
                "x402_identifier_required",
                "policy requires an x402 payment identifier",
            )
        if intent.x402_requirement_id and not intent.x402_requirement_fingerprint:
            return deny(
                "x402_fingerprint_required",
                "x402 payments require the complete requirement fingerprint",
            )
        if intent.x402_requirement_fingerprint and not intent.x402_requirement_id:
            return deny(
                "x402_identifier_required",
                "x402 requirement fingerprints require a replay-protected identifier",
            )

        host = resource_host(intent.resource_url)
        if intent.resource_url and host is None:
            return deny("invalid_resource_host", "x402 resource host is invalid")
        if host and host in policy.blocked_resource_hosts:
            return deny("resource_host_blocked", "x402 resource host is blocked")
        if policy.allowed_resource_hosts and host not in policy.allowed_resource_hosts:
            return deny(
                "resource_host_not_allowed",
                "x402 resource host is not in the policy allowlist",
            )

        return PaymentPolicyDecision(
            authorized=True,
            reason_code="authorized",
            explanation="payment is within deterministic policy",
            policy_id=policy.policy_id,
            payment_id=intent.payment_id,
        )
