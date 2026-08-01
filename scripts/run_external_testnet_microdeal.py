#!/usr/bin/env python3
"""Run one consent-bound external design-partner microdeal on Arc testnet.

The runner is deliberately narrow:

* dry-run is the default and never moves funds;
* execution requires an exact, script-specific confirmation phrase;
* only canonical USDC on ``ARC-TESTNET`` is supported;
* the script never performs an authentication or login flow;
* Gemini is advisory through :class:`CapabilityProductizer`; deterministic
  code owns the SKU contract, price, payment policy, and delivery acceptance;
* one durable idempotency key prevents a replay from executing a second
  transfer; and
* private and redacted public evidence are written atomically with mode 0600.

Expected private customer record shape::

    {
      "customerRecordId": "private-customer-record-id",
      "relationship": {
        "relationshipRecordId": "private-relationship-record-id",
        "classification": "external_design_partner"
      },
      "consent": {
        "consentRecordId": "private-consent-record-id",
        "status": "granted",
        "designPartnerPilot": true,
        "testnetMicrodeal": true,
        "publishRedactedEvidence": true
      },
      "buyerAgentUrl": "https://buyer.example/a2a",
      "claims": [
        {
          "claim": "A bounded claim to verify.",
          "sources": [
            {
              "url": "https://evidence.example/report",
              "title": "Report",
              "excerpt": "Buyer-supplied evidence excerpt.",
              "stance": "support"
            }
          ]
        }
      ]
    }

Additional private customer fields are retained only in private evidence. They
are never sent to Gemini or the fulfillment executor and are checked against
the generated public evidence before publication.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for package_root in (PROJECT_ROOT / "apps" / "api", PROJECT_ROOT / "packages"):
    package_text = str(package_root)
    if package_text not in sys.path:
        sys.path.insert(0, package_text)

from autonomerce.agents import (  # noqa: E402
    CapabilityProductizer,
    DeliveryValidator,
    GeminiDecisionProvider,
)
from autonomerce.contracts import (  # noqa: E402
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
    stable_id,
    usdc_text,
)
from autonomerce.payments import (  # noqa: E402
    ARC_TESTNET_EXPLORER_URL,
    ARC_TESTNET_USDC,
    CircleCLIExecutor,
    ExecutionResult,
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    PaymentPolicyGate,
    PaymentProcessor,
    SQLitePaymentStore,
    arc_testnet_transaction_lookup_factory,
    transaction_lookup_hook,
    verify_receipt,
)
from autonomerce.sales.executors import (  # noqa: E402
    InitialVerificationExecutor,
)
from offerrail import (  # noqa: E402
    PolicyContext,
    capability_to_sku,
    create_proposal,
    make_idempotency_key,
    transition_proposal,
)


TESTNET_EXECUTION_CONFIRMATION = (
    "EXECUTE_ONE_EXTERNAL_CUSTOMER_ARC_TESTNET_MICRODEAL"
)
CHAIN = "ARC-TESTNET"
TOKEN = "USDC"
AMOUNT_USDC = Decimal("0.10")
MAXIMUM_TOTAL_USDC = Decimal("0.10")
MAXIMUM_PAYMENT_COUNT = 1
FULFILLMENT_KIND = "verify-five-claims"
DEFAULT_SELLER_AGENT_URL = "https://autonomerce.example/a2a"
MAX_CUSTOMER_RECORD_BYTES = 1_000_000


ExecutorFactory = Callable[..., Any]
Lookup = Callable[[str], Mapping[str, Any] | None]
LookupFactory = Callable[[], Lookup]
FulfillmentExecutorFactory = Callable[..., Any]


@dataclass(frozen=True)
class RunConfiguration:
    """Owner-controlled paths and wallet bindings for one microdeal."""

    microdeal_id: str
    customer_record_path: Path
    payer_wallet: str
    payee_wallet: str
    circle_cli_binary: Path
    circle_cli_sha256: str
    sqlite_path: Path
    private_evidence_path: Path
    public_evidence_path: Path
    seller_agent_url: str = DEFAULT_SELLER_AGENT_URL
    circle_cli_interpreter: Path | None = None
    circle_cli_interpreter_sha256: str | None = None


@dataclass(frozen=True)
class CustomerRecord:
    """Validated private input; only explicitly public fields may be emitted."""

    raw: Mapping[str, Any]
    customer_record_id: str
    relationship_record_id: str
    consent_record_id: str
    buyer_agent_url: str
    buyer_host: str
    claims: tuple[Mapping[str, Any], ...]
    record_hash: str

    @property
    def buyer_input(self) -> Mapping[str, Any]:
        return {"claims": [dict(claim) for claim in self.claims]}


def _utc_timestamp(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be finite JSON data") from exc


def _required_text(
    value: Any,
    *,
    label: str,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds its size limit")
    if any(ord(character) < 32 for character in text):
        raise ValueError(f"{label} contains control characters")
    return text


def _required_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_true(
    value: Mapping[str, Any],
    names: Sequence[str],
    *,
    label: str,
) -> None:
    present = [name for name in names if name in value]
    if not present or not any(value[name] is True for name in present):
        raise ValueError(f"{label} must be explicitly true")
    if any(value[name] is not True for name in present):
        raise ValueError(f"{label} contains a non-true explicit value")


def _canonical_public_https_url(value: Any, *, label: str) -> tuple[str, str]:
    raw = _required_text(value, label=label, maximum=2_048)
    try:
        parsed = urlsplit(raw)
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port != 443
    ):
        raise ValueError(
            f"{label} must be public HTTPS without credentials, query, fragment, "
            "or a non-default port"
        )
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError(f"{label} has an invalid hostname") from exc
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"{label} must use a public hostname")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not literal.is_global:
            raise ValueError(f"{label} must not use a non-public IP address")
        host = literal.compressed
    host_text = f"[{host}]" if ":" in host else host
    path = parsed.path or "/"
    return urlunsplit(("https", host_text, path, "", "")), host


def _source_url(value: Any, *, label: str) -> str:
    raw = _required_text(value, label=label, maximum=2_048)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and port != 443)
    ):
        raise ValueError(
            f"{label} must be HTTPS without credentials, fragments, or a "
            "non-default port"
        )
    return raw


def _optional_text(
    value: Any,
    *,
    label: str,
    maximum: int,
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds its size limit")
    return text


def _normalize_claims(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 5:
        raise ValueError("customerRecord.claims must contain 1 to 5 claims")
    normalized_claims: list[Mapping[str, Any]] = []
    for claim_index, item in enumerate(value):
        claim = _required_mapping(
            item,
            label=f"customerRecord.claims[{claim_index}]",
        )
        unknown_claim_fields = set(claim) - {"claim", "sources"}
        if unknown_claim_fields:
            raise ValueError(
                f"customerRecord.claims[{claim_index}] contains unsupported fields"
            )
        claim_text = _required_text(
            claim.get("claim"),
            label=f"customerRecord.claims[{claim_index}].claim",
            maximum=8_000,
        )
        raw_sources = claim.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError(
                f"customerRecord.claims[{claim_index}].sources must be non-empty"
            )
        if len(raw_sources) > 25:
            raise ValueError(
                f"customerRecord.claims[{claim_index}].sources exceeds 25 entries"
            )
        sources: list[Mapping[str, str]] = []
        seen_ids: set[str] = set()
        for source_index, source_value in enumerate(raw_sources):
            source = _required_mapping(
                source_value,
                label=(
                    f"customerRecord.claims[{claim_index}].sources[{source_index}]"
                ),
            )
            unknown_source_fields = set(source) - {
                "sourceId",
                "id",
                "url",
                "title",
                "excerpt",
                "stance",
            }
            if unknown_source_fields:
                raise ValueError(
                    "customerRecord claim source contains unsupported fields"
                )
            url = _source_url(
                source.get("url"),
                label=(
                    f"customerRecord.claims[{claim_index}].sources"
                    f"[{source_index}].url"
                ),
            )
            supplied_id = source.get("sourceId", source.get("id"))
            if supplied_id is None:
                source_id = stable_id(
                    "source",
                    claim_index,
                    source_index,
                    url,
                )
            else:
                source_id = _required_text(
                    supplied_id,
                    label="sourceId",
                    maximum=128,
                )
                if not all(
                    character.isalnum() or character in "._:-"
                    for character in source_id
                ):
                    raise ValueError("sourceId contains invalid characters")
            if source_id in seen_ids:
                raise ValueError("claim sources contain duplicate sourceId")
            seen_ids.add(source_id)
            stance = str(source.get("stance", "context")).strip().lower()
            if stance not in {"support", "refute", "context"}:
                raise ValueError(
                    "source.stance must be support, refute, or context"
                )
            sources.append(
                {
                    "sourceId": source_id,
                    "url": url,
                    "title": _optional_text(
                        source.get("title"),
                        label="source.title",
                        maximum=500,
                    ),
                    "excerpt": _optional_text(
                        source.get("excerpt"),
                        label="source.excerpt",
                        maximum=8_000,
                    ),
                    "stance": stance,
                }
            )
        normalized_claims.append({"claim": claim_text, "sources": sources})
    return tuple(normalized_claims)


def _read_customer_record(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError("private customer record could not be read") from exc
    if not raw or len(raw) > MAX_CUSTOMER_RECORD_BYTES:
        raise ValueError("private customer record is empty or exceeds its size limit")
    try:
        decoded = raw.decode("utf-8")
        value = json.loads(
            decoded,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            "private customer record must be strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise ValueError("private customer record must be a JSON object")
    return dict(value)


def _validate_customer_record(value: Mapping[str, Any]) -> CustomerRecord:
    customer_record_id = _required_text(
        value.get("customerRecordId"),
        label="customerRecord.customerRecordId",
        maximum=160,
    )
    relationship = _required_mapping(
        value.get("relationship"),
        label="customerRecord.relationship",
    )
    relationship_record_id = _required_text(
        relationship.get("relationshipRecordId"),
        label="customerRecord.relationship.relationshipRecordId",
        maximum=160,
    )
    classification = _required_text(
        relationship.get("classification"),
        label="customerRecord.relationship.classification",
        maximum=80,
    )
    if classification != "external_design_partner":
        raise ValueError(
            "customer relationship classification must be external_design_partner"
        )

    consent = _required_mapping(
        value.get("consent"),
        label="customerRecord.consent",
    )
    consent_record_id = _required_text(
        consent.get("consentRecordId"),
        label="customerRecord.consent.consentRecordId",
        maximum=160,
    )
    status = _required_text(
        consent.get("status"),
        label="customerRecord.consent.status",
        maximum=32,
    ).lower()
    if status != "granted":
        raise ValueError("customer consent status must be granted")
    _require_true(
        consent,
        ("designPartnerPilot", "participateInDesignPartnerPilot"),
        label="design-partner pilot consent",
    )
    _require_true(
        consent,
        ("testnetMicrodeal", "testnetTransaction"),
        label="testnet microdeal consent",
    )
    _require_true(
        consent,
        ("publishRedactedEvidence", "customerConsentToPublish"),
        label="redacted public evidence consent",
    )

    buyer_agent_url, buyer_host = _canonical_public_https_url(
        value.get("buyerAgentUrl"),
        label="customerRecord.buyerAgentUrl",
    )
    claims = _normalize_claims(value.get("claims"))
    detached = json.loads(_canonical_json_bytes(value).decode("utf-8"))
    record_hash = "sha256:" + hashlib.sha256(
        _canonical_json_bytes(detached)
    ).hexdigest()
    return CustomerRecord(
        raw=detached,
        customer_record_id=customer_record_id,
        relationship_record_id=relationship_record_id,
        consent_record_id=consent_record_id,
        buyer_agent_url=buyer_agent_url,
        buyer_host=buyer_host,
        claims=claims,
        record_hash=record_hash,
    )


def _capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id="external_design_partner_verification",
        name="External design-partner claim verification",
        description=(
            "Verify one to five buyer-supplied claims against cited buyer-supplied "
            "sources and return a bounded evidence artifact."
        ),
        input_schema={
            "type": "object",
            "required": ["claims"],
            "properties": {
                "claims": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                }
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": [
                "artifactType",
                "proposalId",
                "skuId",
                "verdict",
                "verdicts",
                "claimCount",
                "sources",
                "externalTruthVerified",
            ],
            "properties": {
                "artifactType": {"type": "string"},
                "proposalId": {"type": "string"},
                "skuId": {"type": "string"},
                "verdict": {"type": "string"},
                "verdicts": {"type": "array"},
                "claimCount": {"type": "integer"},
                "sources": {"type": "array"},
                "externalTruthVerified": {"type": "boolean"},
            },
        },
        source_kind="manual",
        source_url=DEFAULT_SELLER_AGENT_URL,
        tags=("verification", "evidence", "external-design-partner"),
    )


def _commercial_policy(
    customer: CustomerRecord,
    *,
    microdeal_id: str,
) -> CommercialPolicy:
    return CommercialPolicy(
        policy_id=stable_id("policy", "external-testnet-microdeal", microdeal_id),
        owner_id="autonomerce_external_testnet_owner",
        minimum_price_usdc=AMOUNT_USDC,
        maximum_price_usdc=AMOUNT_USDC,
        maximum_discount_fraction=Decimal("0"),
        maximum_open_proposals=1,
        maximum_tasks_per_hour=1,
        allowed_buyer_hosts=(customer.buyer_host,),
        blocked_buyer_hosts=(),
        allowed_chains=(CHAIN,),
        allowed_token=TOKEN,
        unattended=True,
    )


def _canonical_productized_sku(
    *,
    capability: CapabilityDescriptor,
    policy: CommercialPolicy,
    provider: Any,
) -> tuple[ServiceSKU, Mapping[str, Any]]:
    decision = CapabilityProductizer(provider).productize(
        capability,
        policy,
        maximum_skus=1,
    )
    if len(decision.skus) != 1:
        raise RuntimeError("productizer did not return exactly one authorized SKU")
    advisory_sku = decision.skus[0]
    if (
        advisory_sku.capability_id != capability.capability_id
        or advisory_sku.base_price_usdc != AMOUNT_USDC
        or advisory_sku.input_schema != capability.input_schema
        or advisory_sku.output_schema != capability.output_schema
    ):
        raise RuntimeError("productizer output escaped the fixed capability contract")

    # Gemini controls advisory copy only. Canonical owner-controlled copy keeps
    # the proposal and idempotency key stable if Gemini paraphrases a SKU name.
    sku = capability_to_sku(
        capability,
        name=capability.name,
        outcome=capability.description,
        base_price_usdc=advisory_sku.base_price_usdc,
        acceptance_criteria=advisory_sku.acceptance_criteria,
        maximum_latency_seconds=advisory_sku.maximum_latency_seconds,
        capacity_per_hour=advisory_sku.capacity_per_hour,
    )
    if sku.base_price_usdc != AMOUNT_USDC:
        raise RuntimeError("canonical microdeal SKU price is not exactly 0.10 USDC")
    return sku, decision.to_dict()


def _accepted_proposal(
    *,
    microdeal_id: str,
    customer: CustomerRecord,
    sku: ServiceSKU,
    policy: CommercialPolicy,
    seller_agent_url: str,
) -> Proposal:
    need = BuyerNeed(
        need_id=stable_id(
            "need",
            "external-testnet-microdeal",
            microdeal_id,
            customer.customer_record_id,
            customer.record_hash,
        ),
        buyer_agent_url=customer.buyer_agent_url,
        desired_outcome=sku.outcome,
        maximum_price_usdc=AMOUNT_USDC,
        required_tags=("verification", "evidence"),
        input_payload=customer.buyer_input,
    )
    draft = create_proposal(
        sku=sku,
        policy=policy,
        seller_agent_url=seller_agent_url,
        buyer_need=need,
        problem_observed=(
            f"External design partner requested verification of "
            f"{len(customer.claims)} buyer-supplied claim(s)."
        ),
        price_usdc=AMOUNT_USDC,
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
    accepted = transition_proposal(
        offered,
        ProposalState.ACCEPTED,
        expected_revision=offered.revision,
    )
    if accepted.price_usdc != AMOUNT_USDC:
        raise RuntimeError("accepted proposal price is not exactly 0.10 USDC")
    return accepted


def _payment_intent(
    proposal: Proposal,
    *,
    microdeal_id: str,
    payer_wallet: str,
    payee_wallet: str,
) -> PaymentIntent:
    idempotency_key = make_idempotency_key(
        "external-design-partner-arc-testnet-microdeal",
        microdeal_id,
        usdc_text(AMOUNT_USDC),
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
        metadata={
            "microdealRef": stable_id("microdeal", microdeal_id),
            "externalCustomer": True,
            "fundingSource": "founder_sponsored_testnet",
        },
    )


def _payment_policy(intent: PaymentIntent, *, microdeal_id: str) -> PaymentPolicy:
    return PaymentPolicy(
        policy_id=stable_id("policy", "external-testnet-payment", microdeal_id),
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
    executor = executor_factory(**kwargs)
    if getattr(executor, "mode", None) is not PaymentMode.TESTNET:
        raise ValueError("payment executor must be testnet-only")
    return executor


def _secure_store_files(path: Path) -> None:
    for candidate in (
        path,
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    ):
        try:
            os.chmod(candidate, 0o600)
        except FileNotFoundError:
            # SQLite sidecar files are optional until WAL/SHM creation.
            pass


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
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
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_descriptor = -1
        if directory_descriptor >= 0:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            # A successful os.replace already moved the temporary path.
            pass


def _payment_private_dict(receipt: PaymentReceipt) -> Mapping[str, Any]:
    return {
        "paymentId": receipt.payment_id,
        "proposalId": receipt.proposal_id,
        "idempotencyKey": receipt.idempotency_key,
        "state": receipt.state.value,
        "amountUsdc": usdc_text(receipt.amount_usdc),
        "network": receipt.chain,
        "token": receipt.token,
        "asset": receipt.asset,
        "payerWallet": receipt.payer_wallet,
        "payeeWallet": receipt.payee_wallet,
        "transactionHash": receipt.transaction_hash,
        "explorerUrl": receipt.explorer_url,
        "confirmedAt": receipt.confirmed_at,
    }


def _fulfillment_private_dict(
    *,
    artifact: Mapping[str, Any],
    validation: Any,
    final_proposal: Proposal,
) -> Mapping[str, Any]:
    return {
        "artifact": dict(artifact),
        "artifactHash": validation.receipt.artifact_hash,
        "fulfillmentId": validation.receipt.fulfillment_id,
        "accepted": validation.accepted,
        "acceptanceResults": dict(validation.receipt.acceptance_results),
        "reasonCodes": list(validation.reason_codes),
        "schemaErrors": list(validation.schema_errors),
        "validator": validation.receipt.validator,
        "deliveredAt": validation.receipt.delivered_at,
        "finalProposalState": final_proposal.state.value,
    }


_FORBIDDEN_PUBLIC_KEY_PARTS = (
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "secret",
    "clientsecret",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "email",
    "phone",
    "contact",
    "legalname",
    "participantname",
    "organization",
    "company",
    "postaladdress",
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|github_pat)-?[A-Za-z0-9_]{12,}", re.IGNORECASE),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
)


def _normalized_key(value: Any) -> str:
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def _walk_public_keys(value: Any, *, path: str = "publicEvidence") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = _normalized_key(key)
            if any(part in normalized for part in _FORBIDDEN_PUBLIC_KEY_PARTS):
                raise ValueError(
                    f"{path} contains a customer PII/credential-like field"
                )
            _walk_public_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _walk_public_keys(nested, path=f"{path}[{index}]")


def _private_customer_strings(
    value: Any,
    *,
    path: tuple[str, ...] = (),
) -> list[str]:
    if isinstance(value, Mapping):
        values: list[str] = []
        for key, nested in value.items():
            values.extend(
                _private_customer_strings(nested, path=(*path, str(key)))
            )
        return values
    if isinstance(value, (list, tuple)):
        values = []
        for index, nested in enumerate(value):
            values.extend(
                _private_customer_strings(nested, path=(*path, str(index)))
            )
        return values
    if not isinstance(value, str) or not value:
        return []
    dotted = ".".join(path)
    public_paths = {
        "buyerAgentUrl",
        "relationship.classification",
        "classification",
        "consent.status",
    }
    if dotted in public_paths:
        return []
    return [value]


def _assert_public_evidence_safe(
    payload: Mapping[str, Any],
    *,
    customer_record: Mapping[str, Any],
    allowed_public_values: Sequence[str] = (),
) -> None:
    """Reject generated public evidence containing private customer material."""

    _walk_public_keys(payload)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(encoded):
            raise ValueError("public evidence contains credential-like material")

    allowed = set(allowed_public_values)
    folded_public = encoded.casefold()
    for private_value in _private_customer_strings(customer_record):
        if private_value in allowed:
            continue
        encoded_private = json.dumps(
            private_value,
            ensure_ascii=True,
        ).casefold()
        if encoded_private in folded_public:
            raise ValueError(
                "public evidence contains private customer PII or source material"
            )


def _source_url_hashes(customer: CustomerRecord) -> list[str]:
    hashes = {
        "sha256:"
        + hashlib.sha256(str(source["url"]).encode("utf-8")).hexdigest()
        for claim in customer.claims
        for source in claim["sources"]
    }
    return sorted(hashes)


def _private_evidence(
    *,
    config: RunConfiguration,
    customer: CustomerRecord,
    productization: Mapping[str, Any],
    accepted_proposal: Proposal,
    final_proposal: Proposal,
    payment: PaymentReceipt,
    artifact: Mapping[str, Any],
    validation: Any,
    independent_lookup_count: int,
    replay_verified: bool,
    generated_at: str,
) -> Mapping[str, Any]:
    return {
        "schemaVersion": "autonomerce.external_testnet_microdeal.private.v1",
        "recordKind": "external_testnet_microdeal",
        "evidenceClassification": "testnet",
        "microdealId": config.microdeal_id,
        "customerRecordHash": customer.record_hash,
        "customerRecord": dict(customer.raw),
        "customerRelationshipRecordId": customer.relationship_record_id,
        "consentRecordId": customer.consent_record_id,
        "productization": dict(productization),
        "acceptedProposal": accepted_proposal.to_dict(),
        "finalProposal": final_proposal.to_dict(),
        "payment": _payment_private_dict(payment),
        "fulfillment": _fulfillment_private_dict(
            artifact=artifact,
            validation=validation,
            final_proposal=final_proposal,
        ),
        "independentLookupCount": independent_lookup_count,
        "idempotentReplayVerified": replay_verified,
        "externalCustomer": True,
        "fundingSource": "founder_sponsored_testnet",
        "countedAsRevenue": False,
        "payingCustomer": False,
        "evidenceGeneratedAt": generated_at,
    }


def _public_evidence(
    *,
    config: RunConfiguration,
    customer: CustomerRecord,
    productization: Mapping[str, Any],
    proposal: Proposal,
    payment: PaymentReceipt,
    validation: Any,
    generated_at: str,
) -> Mapping[str, Any]:
    accepted = validation.accepted is True
    transaction_hash = payment.transaction_hash
    if not transaction_hash:
        raise RuntimeError("confirmed payment is missing a transaction hash")
    evidence = {
        "schemaVersion": "autonomerce.external_testnet_microdeal.public.v1",
        "recordKind": "external_testnet_microdeal",
        "synthetic": False,
        "evidenceClassification": "testnet",
        "microdealId": stable_id("microdeal", config.microdeal_id),
        "customerRecordId": stable_id(
            "customer",
            customer.customer_record_id,
            customer.record_hash,
        ),
        "customerRelationship": "external_design_partner",
        "customerRelationshipRecordId": stable_id(
            "relationship",
            customer.relationship_record_id,
        ),
        "consentRecordId": stable_id("consent", customer.consent_record_id),
        "customerConsentToPublish": True,
        "buyerAgentUrl": customer.buyer_agent_url,
        "proposalId": proposal.proposal_id,
        "paymentId": payment.payment_id,
        "fulfillmentId": validation.receipt.fulfillment_id,
        "network": CHAIN,
        "token": TOKEN,
        "asset": ARC_TESTNET_USDC,
        "amountUsdc": usdc_text(payment.amount_usdc),
        "movesFunds": True,
        "transactionHash": transaction_hash,
        "explorerUrl": (
            payment.explorer_url
            or f"{ARC_TESTNET_EXPLORER_URL}/tx/{transaction_hash}"
        ),
        "confirmedAt": payment.confirmed_at,
        "payerWallet": None,
        "payeeWallet": None,
        "externalCustomer": True,
        "fundingSource": "founder_sponsored_testnet",
        "countedAsRevenue": False,
        "payingCustomer": False,
        "claimCount": len(customer.claims),
        "sourceUrlCount": sum(
            len(claim["sources"]) for claim in customer.claims
        ),
        "sourceUrlHashes": _source_url_hashes(customer),
        "delivered": accepted,
        "acceptanceVerdict": "accepted" if accepted else "rejected",
        "acceptanceResults": dict(validation.receipt.acceptance_results),
        "artifactHash": validation.receipt.artifact_hash,
        "validator": validation.receipt.validator,
        "independentLookupVerified": True,
        "idempotentReplayVerified": True,
        "productizerProvider": productization.get("provider"),
        "productizerModel": productization.get("model"),
        "evidenceGeneratedAt": generated_at,
        "notes": [
            "External design-partner testnet evidence only.",
            "Founder-sponsored testnet funding; countedAsRevenue=false.",
            "The external design partner did not fund this transfer and is not "
            + "classified as a paying customer.",
            "Customer identity, claims, source URLs, source excerpts, wallets, "
            + "credentials, and the internal idempotency key are omitted.",
            "Delivery and acceptance reflect deterministic contract validation.",
        ],
    }
    _assert_public_evidence_safe(
        evidence,
        customer_record=customer.raw,
        allowed_public_values=(customer.buyer_agent_url,),
    )
    return evidence


def _validate_configuration(config: RunConfiguration) -> str:
    microdeal_id = _required_text(
        config.microdeal_id,
        label="microdeal_id",
        maximum=160,
    )
    evidence_paths = {
        config.private_evidence_path.resolve(),
        config.public_evidence_path.resolve(),
        config.sqlite_path.resolve(),
        config.customer_record_path.resolve(),
    }
    if len(evidence_paths) != 4:
        raise ValueError(
            "customer record, SQLite, private evidence, and public evidence paths "
            "must be different"
        )
    if (config.circle_cli_interpreter is None) != (
        config.circle_cli_interpreter_sha256 is None
    ):
        raise ValueError(
            "Circle CLI interpreter path and SHA-256 must be provided together"
        )
    seller_url, _ = _canonical_public_https_url(
        config.seller_agent_url,
        label="seller_agent_url",
    )
    if seller_url != config.seller_agent_url:
        raise ValueError("seller_agent_url must already be canonical")
    return microdeal_id


def _replay_execution_result(receipt: PaymentReceipt) -> ExecutionResult:
    return ExecutionResult(
        state="CONFIRMED",
        amount_usdc=receipt.amount_usdc,
        chain=receipt.chain,
        payer_wallet=receipt.payer_wallet,
        payee_wallet=receipt.payee_wallet,
        transaction_hash=receipt.transaction_hash,
        confirmed_at=receipt.confirmed_at,
        explorer_url=receipt.explorer_url,
        simulated=False,
        provider_reference="durable-idempotent-replay",
        token=receipt.token,
        asset=receipt.asset,
    )


def run_microdeal(
    config: RunConfiguration,
    *,
    dry_run: bool = True,
    confirmation: str | None = None,
    provider: Any | None = None,
    executor_factory: ExecutorFactory = CircleCLIExecutor,
    lookup_factory: LookupFactory = arc_testnet_transaction_lookup_factory,
    fulfillment_executor_factory: FulfillmentExecutorFactory = (
        InitialVerificationExecutor
    ),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Preflight or execute one deterministic external testnet microdeal."""

    if dry_run:
        if confirmation is not None:
            raise ValueError("dry-run mode cannot include an execution confirmation")
    elif confirmation != TESTNET_EXECUTION_CONFIRMATION:
        raise ValueError(
            "exact external Arc testnet microdeal confirmation is required"
        )

    microdeal_id = _validate_configuration(config)
    customer = _validate_customer_record(
        _read_customer_record(config.customer_record_path)
    )
    capability = _capability()
    commercial_policy = _commercial_policy(
        customer,
        microdeal_id=microdeal_id,
    )
    productizer_provider = (
        GeminiDecisionProvider() if provider is None else provider
    )
    sku, productization = _canonical_productized_sku(
        capability=capability,
        policy=commercial_policy,
        provider=productizer_provider,
    )
    proposal = _accepted_proposal(
        microdeal_id=microdeal_id,
        customer=customer,
        sku=sku,
        policy=commercial_policy,
        seller_agent_url=config.seller_agent_url,
    )
    intent = _payment_intent(
        proposal,
        microdeal_id=microdeal_id,
        payer_wallet=config.payer_wallet,
        payee_wallet=config.payee_wallet,
    )
    payment_policy = _payment_policy(intent, microdeal_id=microdeal_id)

    config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLitePaymentStore(config.sqlite_path)
    _secure_store_files(config.sqlite_path)
    existing_before = store.get(intent.idempotency_key)
    executor = _build_executor(config, executor_factory=executor_factory)
    # Preflight the exact transfer command without invoking it.
    executor.build_argv(intent)
    lookup = lookup_factory()
    if not callable(lookup):
        raise ValueError("lookup_factory must return a callable lookup")
    lookup_calls: list[str] = []

    def audited_lookup(transaction_hash: str) -> Mapping[str, Any] | None:
        lookup_calls.append(transaction_hash)
        return lookup(transaction_hash)

    lookup_hook = transaction_lookup_hook(audited_lookup)

    if dry_run:
        if existing_before is None:
            decision = PaymentPolicyGate().evaluate(
                intent,
                payment_policy,
                store.snapshot(payment_policy.policy_id),
            )
            authorized = decision.authorized
            reason_code = decision.reason_code
        else:
            authorized = existing_before.state is PaymentState.CONFIRMED
            reason_code = (
                "idempotent_replay_available"
                if authorized
                else "existing_payment_not_confirmed"
            )
        return {
            "mode": "dry-run",
            "transferExecuted": False,
            "transferAuthorized": False,
            "policyWouldAuthorize": authorized,
            "policyReasonCode": reason_code,
            "proposalState": proposal.state.value,
            "proposalId": proposal.proposal_id,
            "network": CHAIN,
            "token": TOKEN,
            "asset": ARC_TESTNET_USDC,
            "amountUsdc": usdc_text(intent.amount_usdc),
            "maximumPerPaymentUsdc": usdc_text(
                payment_policy.maximum_per_payment_usdc
            ),
            "maximumTotalUsdc": usdc_text(
                payment_policy.maximum_total_usdc
            ),
            "maximumPaymentCount": payment_policy.maximum_payment_count,
            "claimCount": len(customer.claims),
            "buyerAgentUrl": customer.buyer_agent_url,
            "externalCustomer": True,
            "fundingSource": "founder_sponsored_testnet",
            "countedAsRevenue": False,
            "payingCustomer": False,
            "delivered": False,
            "acceptanceVerdict": "pending",
            "evidenceWritten": False,
            "durableStore": str(config.sqlite_path),
            "interpreterPinned": config.circle_cli_interpreter is not None,
        }

    processor = PaymentProcessor(
        policy=payment_policy,
        store=store,
        executor=executor,
        verification_hooks=(lookup_hook,),
    )
    receipt = processor.pay(intent)
    replay = processor.pay(intent)
    _secure_store_files(config.sqlite_path)
    if receipt != replay:
        raise RuntimeError("idempotent replay returned different payment evidence")
    if receipt.state is not PaymentState.CONFIRMED:
        raise RuntimeError("payment did not reach confirmed state")

    if existing_before is not None:
        replay_verification = verify_receipt(
            receipt,
            intent,
            _replay_execution_result(receipt),
            mode=PaymentMode.TESTNET,
            hooks=(lookup_hook,),
        )
        if not replay_verification.verified:
            raise RuntimeError(
                "durable replay failed independent transaction lookup verification"
            )
    if not lookup_calls or any(
        transaction_hash.lower() != (receipt.transaction_hash or "").lower()
        for transaction_hash in lookup_calls
    ):
        raise RuntimeError(
            "independent transaction lookup did not verify the confirmed transfer"
        )

    paid = transition_proposal(
        proposal,
        ProposalState.PAID,
        expected_revision=proposal.revision,
    )
    fulfilling = transition_proposal(
        paid,
        ProposalState.FULFILLING,
        expected_revision=paid.revision,
    )
    fulfillment_executor = fulfillment_executor_factory(
        sku_contracts={sku.sku_id: FULFILLMENT_KIND}
    )
    artifact = fulfillment_executor.execute(
        fulfilling,
        context={"buyerInput": customer.buyer_input},
    )
    if not isinstance(artifact, Mapping):
        raise RuntimeError("InitialVerificationExecutor returned a non-object artifact")
    generated_at = _utc_timestamp(now)
    validation = DeliveryValidator().validate(
        sku=sku,
        proposal=fulfilling,
        payment=receipt,
        artifact=artifact,
        delivered_at=generated_at,
    )
    final_proposal = transition_proposal(
        fulfilling,
        (
            ProposalState.DELIVERED
            if validation.accepted
            else ProposalState.FAILED
        ),
        expected_revision=fulfilling.revision,
    )

    private_evidence = _private_evidence(
        config=config,
        customer=customer,
        productization=productization,
        accepted_proposal=proposal,
        final_proposal=final_proposal,
        payment=receipt,
        artifact=artifact,
        validation=validation,
        independent_lookup_count=len(lookup_calls),
        replay_verified=True,
        generated_at=generated_at,
    )
    public_evidence = _public_evidence(
        config=config,
        customer=customer,
        productization=productization,
        proposal=proposal,
        payment=receipt,
        validation=validation,
        generated_at=generated_at,
    )
    # Write the full private audit first. If public publication fails, no public
    # artifact is produced without its corresponding private source record.
    _atomic_write_json(config.private_evidence_path, private_evidence)
    _atomic_write_json(config.public_evidence_path, public_evidence)

    return {
        "mode": "external-testnet-microdeal",
        "transferExecuted": existing_before is None,
        "movesFunds": True,
        "proposalId": proposal.proposal_id,
        "paymentId": receipt.payment_id,
        "transactionHash": receipt.transaction_hash,
        "explorerUrl": public_evidence["explorerUrl"],
        "fulfillmentId": validation.receipt.fulfillment_id,
        "idempotentReplayVerified": True,
        "independentLookupVerified": True,
        "externalCustomer": True,
        "fundingSource": "founder_sponsored_testnet",
        "countedAsRevenue": False,
        "payingCustomer": False,
        "delivered": validation.accepted,
        "acceptanceVerdict": (
            "accepted" if validation.accepted else "rejected"
        ),
        "privateEvidencePath": str(config.private_evidence_path),
        "publicEvidencePath": str(config.public_evidence_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run by default, or execute one consent-bound 0.10 USDC "
            "external design-partner microdeal on Arc testnet."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="explicitly select the default no-transfer preflight",
    )
    mode.add_argument(
        "--confirm-testnet-microdeal",
        metavar="PHRASE",
        help=f"must equal exactly: {TESTNET_EXECUTION_CONFIRMATION}",
    )
    parser.add_argument("--microdeal-id", required=True)
    parser.add_argument("--customer-record", required=True, type=Path)
    parser.add_argument("--payer-wallet", required=True)
    parser.add_argument("--payee-wallet", required=True)
    parser.add_argument(
        "--seller-agent-url",
        default=DEFAULT_SELLER_AGENT_URL,
        help="canonical public HTTPS seller A2A URL",
    )
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
    parser.add_argument("--private-evidence-path", required=True, type=Path)
    parser.add_argument("--public-evidence-path", required=True, type=Path)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    provider: Any | None = None,
    executor_factory: ExecutorFactory = CircleCLIExecutor,
    lookup_factory: LookupFactory = arc_testnet_transaction_lookup_factory,
    fulfillment_executor_factory: FulfillmentExecutorFactory = (
        InitialVerificationExecutor
    ),
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if (
        args.confirm_testnet_microdeal is not None
        and args.confirm_testnet_microdeal != TESTNET_EXECUTION_CONFIRMATION
    ):
        parser.error(
            "--confirm-testnet-microdeal did not match the exact required phrase"
        )
    if (args.circle_cli_interpreter is None) != (
        args.circle_cli_interpreter_sha256 is None
    ):
        parser.error(
            "--circle-cli-interpreter and "
            "--circle-cli-interpreter-sha256 must be provided together"
        )
    config = RunConfiguration(
        microdeal_id=args.microdeal_id,
        customer_record_path=args.customer_record,
        payer_wallet=args.payer_wallet,
        payee_wallet=args.payee_wallet,
        seller_agent_url=args.seller_agent_url,
        circle_cli_binary=args.circle_cli_binary,
        circle_cli_sha256=args.circle_cli_sha256,
        circle_cli_interpreter=args.circle_cli_interpreter,
        circle_cli_interpreter_sha256=args.circle_cli_interpreter_sha256,
        sqlite_path=args.sqlite_path,
        private_evidence_path=args.private_evidence_path,
        public_evidence_path=args.public_evidence_path,
    )
    result = run_microdeal(
        config,
        dry_run=args.confirm_testnet_microdeal is None,
        confirmation=args.confirm_testnet_microdeal,
        provider=provider,
        executor_factory=executor_factory,
        lookup_factory=lookup_factory,
        fulfillment_executor_factory=fulfillment_executor_factory,
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
