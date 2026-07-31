"""OfferRail deterministic commercial domain core."""

from .catalog import (
    build_sku_catalog,
    capability_to_sku,
    productize_capabilities,
    productize_capability,
)
from .idempotency import (
    IdempotencyConflict,
    IdempotencyError,
    IdempotencyFailed,
    IdempotencyInProgress,
    IdempotencyRecord,
    IdempotencyReservation,
    IdempotencyStatus,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    make_idempotency_key,
    request_fingerprint,
)
from .negotiation import (
    bounded_negotiate,
    evaluate_counteroffer,
    negotiate_counteroffer,
)
from .policy import (
    PolicyContext,
    PolicyDenied,
    PolicyEvaluation,
    evaluate_commercial_policy,
    evaluate_policy,
    require_policy_approval,
)
from .proposals import (
    ALLOWED_PROPOSAL_TRANSITIONS,
    ProposalTransitionError,
    can_transition_proposal,
    create_proposal,
    transition_proposal,
)
from .receipts import (
    CommercialReceipt,
    CommercialReceiptLedger,
    ReceiptConflict,
    ReceiptError,
    ReceiptLedger,
    redact_commercial_data,
)

__all__ = [
    "ALLOWED_PROPOSAL_TRANSITIONS",
    "CommercialReceipt",
    "CommercialReceiptLedger",
    "IdempotencyConflict",
    "IdempotencyError",
    "IdempotencyFailed",
    "IdempotencyInProgress",
    "IdempotencyRecord",
    "IdempotencyReservation",
    "IdempotencyStatus",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "PolicyContext",
    "PolicyDenied",
    "PolicyEvaluation",
    "ProposalTransitionError",
    "ReceiptConflict",
    "ReceiptError",
    "ReceiptLedger",
    "bounded_negotiate",
    "build_sku_catalog",
    "can_transition_proposal",
    "capability_to_sku",
    "create_proposal",
    "evaluate_commercial_policy",
    "evaluate_counteroffer",
    "evaluate_policy",
    "make_idempotency_key",
    "negotiate_counteroffer",
    "productize_capabilities",
    "productize_capability",
    "redact_commercial_data",
    "request_fingerprint",
    "require_policy_approval",
    "transition_proposal",
]
