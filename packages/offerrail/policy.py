"""Fail-closed deterministic commercial policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable
from urllib.parse import urlsplit

from autonomerce.contracts import (
    CommercialPolicy,
    ContractError,
    Proposal,
    ProposalState,
    ServiceSKU,
)

from ._canonical import parse_timestamp


@dataclass(frozen=True)
class PolicyContext:
    chain: str = "BASE"
    token: str = "USDC"
    current_open_proposals: int = 0
    current_tasks_last_hour: int = 0
    current_sku_tasks_last_hour: int = 0
    reserving_new_proposal: bool | None = None
    now: str | datetime | None = None


@dataclass(frozen=True)
class PolicyEvaluation:
    allowed: bool
    policy_id: str
    proposal_id: str
    reason_codes: tuple[str, ...] = ()

    @property
    def reason_code(self) -> str:
        return "policy_allowed" if self.allowed else self.reason_codes[0]


class PolicyDenied(ContractError):
    """Raised when deterministic commercial policy does not authorize an action."""

    def __init__(self, evaluation: PolicyEvaluation):
        self.evaluation = evaluation
        super().__init__(
            "commercial policy denied proposal: "
            + ", ".join(evaluation.reason_codes)
        )


def _append_once(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _nonnegative_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _hostname_from_url(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("buyer URL must be text")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid buyer URL") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ContractError("buyer URL must be absolute HTTP(S) without credentials")
    if port is not None and not 1 <= port <= 65535:
        raise ContractError("invalid buyer URL port")
    try:
        return parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ContractError("invalid buyer hostname") from exc


def _normalize_host_rule(value: str) -> tuple[str, bool]:
    text = value.strip().lower()
    if not text:
        raise ContractError("empty policy host rule")
    include_subdomains = text.startswith("*.")
    if include_subdomains:
        text = text[2:]
    if "://" in text:
        text = _hostname_from_url(text)
    else:
        text = text.rstrip(".")
        if any(character in text for character in "/?#@"):
            raise ContractError("invalid policy host rule")
        try:
            text = text.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ContractError("invalid policy host rule") from exc
    if not text or text.startswith(".") or text.endswith(".") or ".." in text:
        raise ContractError("invalid policy host rule")
    return text, include_subdomains


def _matches_host(hostname: str, rule: tuple[str, bool]) -> bool:
    expected, _include_subdomains = rule
    return hostname == expected or hostname.endswith(f".{expected}")


def _normalized_upper(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(value.strip().upper() for value in values if value.strip())


def evaluate_commercial_policy(
    policy: CommercialPolicy,
    sku: ServiceSKU,
    proposal: Proposal,
    *,
    context: PolicyContext | None = None,
    chain: str | None = None,
    token: str | None = None,
    current_open_proposals: int | None = None,
    current_tasks_last_hour: int | None = None,
    current_sku_tasks_last_hour: int | None = None,
    reserving_new_proposal: bool | None = None,
    now: str | datetime | None = None,
) -> PolicyEvaluation:
    """Evaluate all deterministic commercial bounds and return every denial.

    Explicit keyword values override ``context``. Invalid runtime context is
    converted into a denial instead of being treated as zero capacity usage.
    """

    if not isinstance(policy, CommercialPolicy):
        raise ContractError("policy must be a CommercialPolicy")
    if not isinstance(sku, ServiceSKU):
        raise ContractError("sku must be a ServiceSKU")
    if not isinstance(proposal, Proposal):
        raise ContractError("proposal must be a Proposal")
    if context is not None and not isinstance(context, PolicyContext):
        raise ContractError("context must be a PolicyContext")
    base = context or PolicyContext()
    selected_chain = base.chain if chain is None else chain
    selected_token = base.token if token is None else token
    open_count = (
        base.current_open_proposals
        if current_open_proposals is None
        else current_open_proposals
    )
    task_count = (
        base.current_tasks_last_hour
        if current_tasks_last_hour is None
        else current_tasks_last_hour
    )
    sku_task_count = (
        base.current_sku_tasks_last_hour
        if current_sku_tasks_last_hour is None
        else current_sku_tasks_last_hour
    )
    selected_reserving = (
        base.reserving_new_proposal
        if reserving_new_proposal is None
        else reserving_new_proposal
    )
    if selected_reserving is None:
        selected_reserving = proposal.state == ProposalState.DRAFT
    selected_now = base.now if now is None else now
    reasons: list[str] = []

    if policy.unattended is not True:
        _append_once(reasons, "policy_unattended_disabled")
    if not isinstance(proposal.state, ProposalState):
        _append_once(reasons, "invalid_proposal_state")
    if proposal.sku_id != sku.sku_id:
        _append_once(reasons, "sku_mismatch")
    if proposal.state in {
        ProposalState.DECLINED,
        ProposalState.EXPIRED,
        ProposalState.PAID,
        ProposalState.FULFILLING,
        ProposalState.DELIVERED,
        ProposalState.FAILED,
    }:
        _append_once(reasons, "proposal_state_not_commercially_active")

    if proposal.price_usdc < policy.minimum_price_usdc:
        _append_once(reasons, "price_below_policy_minimum")
    if proposal.price_usdc > policy.maximum_price_usdc:
        _append_once(reasons, "price_above_policy_maximum")
    discount_floor = sku.base_price_usdc * (
        Decimal("1") - policy.maximum_discount_fraction
    )
    if proposal.price_usdc < discount_floor:
        _append_once(reasons, "discount_exceeds_policy")
    if proposal.delivery_seconds > sku.maximum_latency_seconds:
        _append_once(reasons, "delivery_exceeds_sku_latency")

    if not isinstance(selected_chain, str) or not selected_chain.strip():
        _append_once(reasons, "invalid_chain")
    elif selected_chain.strip().upper() not in _normalized_upper(policy.allowed_chains):
        _append_once(reasons, "chain_not_allowed")
    if (
        not isinstance(selected_token, str)
        or not selected_token.strip()
        or not isinstance(policy.allowed_token, str)
        or not policy.allowed_token.strip()
    ):
        _append_once(reasons, "invalid_token")
    elif selected_token.strip().upper() != policy.allowed_token.strip().upper():
        _append_once(reasons, "token_not_allowed")

    try:
        buyer_host = _hostname_from_url(proposal.buyer_agent_url)
    except ContractError:
        buyer_host = ""
        _append_once(reasons, "invalid_buyer_url")
    try:
        blocked_rules = tuple(
            _normalize_host_rule(value) for value in policy.blocked_buyer_hosts
        )
        allowed_rules = tuple(
            _normalize_host_rule(value) for value in policy.allowed_buyer_hosts
        )
    except ContractError:
        blocked_rules = ()
        allowed_rules = ()
        _append_once(reasons, "invalid_policy_host_rule")
    if buyer_host and any(_matches_host(buyer_host, rule) for rule in blocked_rules):
        _append_once(reasons, "buyer_blocked")
    if (
        buyer_host
        and allowed_rules
        and not any(_matches_host(buyer_host, rule) for rule in allowed_rules)
    ):
        _append_once(reasons, "buyer_not_allowlisted")

    valid_open_count = _nonnegative_count(open_count)
    valid_task_count = _nonnegative_count(task_count)
    valid_sku_count = _nonnegative_count(sku_task_count)
    if (
        valid_open_count is None
        or valid_task_count is None
        or valid_sku_count is None
        or not isinstance(selected_reserving, bool)
    ):
        _append_once(reasons, "invalid_capacity_context")
    else:
        if (
            selected_reserving
            and valid_open_count >= policy.maximum_open_proposals
        ):
            _append_once(reasons, "open_proposal_capacity_exceeded")
        if valid_task_count >= policy.maximum_tasks_per_hour:
            _append_once(reasons, "hourly_task_capacity_exceeded")
        if valid_sku_count >= sku.capacity_per_hour:
            _append_once(reasons, "sku_capacity_exceeded")

    if proposal.expires_at is not None:
        try:
            expires_at = parse_timestamp(
                proposal.expires_at, field_name="proposal expires_at"
            )
            current = (
                datetime.now(timezone.utc)
                if selected_now is None
                else parse_timestamp(selected_now, field_name="policy now")
            )
            if current >= expires_at:
                _append_once(reasons, "proposal_expired")
        except ContractError:
            _append_once(reasons, "invalid_proposal_expiry")
    elif selected_now is not None:
        try:
            parse_timestamp(selected_now, field_name="policy now")
        except ContractError:
            _append_once(reasons, "invalid_policy_now")

    return PolicyEvaluation(
        allowed=not reasons,
        policy_id=policy.policy_id,
        proposal_id=proposal.proposal_id,
        reason_codes=tuple(reasons),
    )


def require_policy_approval(
    policy: CommercialPolicy,
    sku: ServiceSKU,
    proposal: Proposal,
    **kwargs: object,
) -> PolicyEvaluation:
    evaluation = evaluate_commercial_policy(policy, sku, proposal, **kwargs)
    if not evaluation.allowed:
        raise PolicyDenied(evaluation)
    return evaluation


evaluate_policy = evaluate_commercial_policy
