"""Fail-closed seller-agent executors for live Autonomerce composition.

The built-in executor evaluates only buyer-supplied evidence.  The optional
HTTPS executor uses an exact owner allowlist and pins a previously validated
public IP for the TLS connection so a second DNS lookup cannot bypass policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import inspect
import ipaddress
import json
import math
import os
import socket
import ssl
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import SplitResult, urlsplit, urlunsplit

from autonomerce.agents.base import (
    DecisionProvider,
    DecisionRequest,
    ProviderResponseError,
    normalize_decision_json,
    provider_identity,
)
from autonomerce.contracts import Proposal


class SellerExecutorError(RuntimeError):
    """A seller executor cannot complete safely."""


class SellerExecutorConfigurationError(SellerExecutorError):
    """Owner-controlled executor configuration is absent or invalid."""


class SellerInputError(SellerExecutorError, ValueError):
    """Buyer input is missing, malformed, or outside the declared SKU."""


class SellerTransportError(SellerExecutorError):
    """A remote seller response failed the egress or JSON contract."""


_SKU_KINDS = frozenset(
    {"verify-one-claim", "verify-five-claims", "evidence-pack"}
)
_DEFAULT_SKUS = {
    "verify-one-claim": "verify-one-claim",
    "verify-five-claims": "verify-five-claims",
    "evidence-pack": "evidence-pack",
}
_MAX_CLAIM_CHARS = 8_000
_MAX_SOURCE_EXCERPT_CHARS = 8_000
_MAX_SOURCES_PER_CLAIM = 25
_EVIDENCE_SCOPE = "buyer_supplied_sources_only"
_LIMITATION = (
    "External truth was not independently verified; every non-abstain verdict "
    "is limited to cited buyer-supplied evidence."
)


INITIAL_VERIFICATION_SKU_OUTPUT_SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    "verify-one-claim": {
        "type": "object",
        "required": [
            "artifactType",
            "proposalId",
            "skuId",
            "verdict",
            "claim",
            "evidence",
            "sources",
            "externalTruthVerified",
        ],
    },
    "verify-five-claims": {
        "type": "object",
        "required": [
            "artifactType",
            "proposalId",
            "skuId",
            "verdict",
            "verdicts",
            "claimCount",
            "externalTruthVerified",
        ],
    },
    "evidence-pack": {
        "type": "object",
        "required": [
            "artifactType",
            "proposalId",
            "skuId",
            "verdict",
            "verdicts",
            "sources",
            "evidencePack",
            "externalTruthVerified",
        ],
    },
}


def _finite_json_bytes(value: Any, *, label: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SellerInputError(f"{label} must be finite JSON data") from exc


def _bounded_string(
    value: Any,
    *,
    label: str,
    maximum: int,
    required: bool = True,
) -> str:
    if not isinstance(value, str):
        raise SellerInputError(f"{label} must be a string")
    text = value.strip()
    if required and not text:
        raise SellerInputError(f"{label} is required")
    if len(text) > maximum:
        raise SellerInputError(f"{label} exceeds its size limit")
    return text


def _source_id(source: Mapping[str, Any]) -> str:
    supplied = source.get("sourceId", source.get("id"))
    if supplied is not None:
        value = _bounded_string(
            supplied, label="sourceId", maximum=128
        )
        if not all(character.isalnum() or character in "._:-" for character in value):
            raise SellerInputError("sourceId contains invalid characters")
        return value
    material = "\x00".join(
        (
            str(source.get("url", "")),
            str(source.get("title", "")),
            str(source.get("excerpt", "")),
        )
    )
    return "src_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _normalize_evidence_url(value: Any) -> str:
    raw = _bounded_string(value, label="source.url", maximum=2_048)
    parsed = urlsplit(raw)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SellerInputError(
            "source.url must be an HTTPS URL without credentials or fragments"
        )
    return raw


def _normalize_sources(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise SellerInputError("buyerInput.sources must be a JSON array")
    if len(value) > _MAX_SOURCES_PER_CLAIM:
        raise SellerInputError("buyerInput.sources exceeds the SKU limit")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise SellerInputError(f"buyerInput.sources[{index}] must be an object")
        source_id = _source_id(item)
        if source_id in seen:
            raise SellerInputError("buyerInput.sources contains duplicate sourceId")
        seen.add(source_id)
        stance = str(item.get("stance", "context")).strip().lower()
        if stance not in {"support", "refute", "context"}:
            raise SellerInputError(
                "source.stance must be support, refute, or context"
            )
        normalized.append(
            {
                "sourceId": source_id,
                "url": _normalize_evidence_url(item.get("url")),
                "title": _bounded_string(
                    item.get("title", ""),
                    label="source.title",
                    maximum=500,
                    required=False,
                ),
                "excerpt": _bounded_string(
                    item.get("excerpt", ""),
                    label="source.excerpt",
                    maximum=_MAX_SOURCE_EXCERPT_CHARS,
                    required=False,
                ),
                "declaredStance": stance,
            }
        )
    return normalized


class DeterministicEvidenceDecisionProvider:
    """Credential-free provider that uses explicit source stances only."""

    provider_name = "offline"
    model_name = "supplied-evidence-rules-v1"

    def generate_json(self, request: DecisionRequest) -> Mapping[str, Any]:
        if request.operation != "verify_claim_against_supplied_evidence":
            raise ProviderResponseError(
                f"unsupported deterministic evidence operation {request.operation!r}"
            )
        sources = request.payload.get("sources", ())
        support = [
            source
            for source in sources
            if source.get("excerpt") and source.get("declaredStance") == "support"
        ]
        refute = [
            source
            for source in sources
            if source.get("excerpt") and source.get("declaredStance") == "refute"
        ]
        if support and not refute:
            verdict = "support"
            selected = support
        elif refute and not support:
            verdict = "refute"
            selected = refute
        else:
            verdict = "abstain"
            selected = []
        return {
            "verdict": verdict,
            "evidence": [
                {"sourceId": source["sourceId"], "stance": verdict}
                for source in selected
            ],
        }


def _decision_request(
    claim: str, sources: Sequence[Mapping[str, str]]
) -> DecisionRequest:
    return DecisionRequest(
        operation="verify_claim_against_supplied_evidence",
        instruction=(
            "Assess only the supplied source excerpts. Return support or refute "
            "only when cited supplied evidence directly warrants it; otherwise "
            "abstain. Do not assert independent external truth."
        ),
        payload={
            "claim": claim,
            "sources": list(sources),
            "evidenceScope": _EVIDENCE_SCOPE,
        },
        response_schema={
            "type": "object",
            "required": ["verdict", "evidence"],
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["support", "refute", "abstain"],
                },
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["sourceId", "stance"],
                    },
                },
            },
        },
    )


def _safe_decision(
    provider: DecisionProvider,
    claim: str,
    sources: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    decision = normalize_decision_json(
        provider.generate_json(_decision_request(claim, sources))
    )
    verdict = str(decision.get("verdict", "")).strip().lower()
    if verdict not in {"support", "refute", "abstain"}:
        raise ProviderResponseError("verification provider returned an invalid verdict")
    by_id = {source["sourceId"]: source for source in sources}
    evidence: list[dict[str, str]] = []
    raw_evidence = decision.get("evidence", ())
    if not isinstance(raw_evidence, (list, tuple)):
        raise ProviderResponseError("verification evidence must be a JSON array")
    for item in raw_evidence:
        if not isinstance(item, Mapping):
            raise ProviderResponseError("verification evidence entries must be objects")
        source_id = str(item.get("sourceId", "")).strip()
        stance = str(item.get("stance", "")).strip().lower()
        source = by_id.get(source_id)
        if (
            source is None
            or not source["excerpt"]
            or stance not in {"support", "refute", "context"}
        ):
            continue
        evidence.append(
            {
                "sourceId": source_id,
                "url": source["url"],
                "title": source["title"],
                "excerpt": source["excerpt"],
                "stance": stance,
            }
        )
    if verdict in {"support", "refute"} and not any(
        item["stance"] == verdict for item in evidence
    ):
        verdict = "abstain"
        evidence = []
    return {
        "claim": claim,
        "verdict": verdict,
        "evidence": evidence,
        "externalTruthVerified": False,
    }


def _claims_for_sku(
    buyer_input: Mapping[str, Any], kind: str
) -> list[tuple[str, list[dict[str, str]]]]:
    maximum = 1 if kind == "verify-one-claim" else 5
    global_sources = _normalize_sources(buyer_input.get("sources", ()))
    raw_claims = buyer_input.get("claims")
    if raw_claims is None:
        claim = _bounded_string(
            buyer_input.get("claim"),
            label="buyerInput.claim",
            maximum=_MAX_CLAIM_CHARS,
        )
        return [(claim, global_sources)]
    if not isinstance(raw_claims, (list, tuple)) or not raw_claims:
        raise SellerInputError("buyerInput.claims must be a non-empty JSON array")
    if len(raw_claims) > maximum:
        raise SellerInputError("buyerInput.claims exceeds the declared SKU limit")
    claims: list[tuple[str, list[dict[str, str]]]] = []
    for index, item in enumerate(raw_claims):
        if isinstance(item, str):
            claim = _bounded_string(
                item,
                label=f"buyerInput.claims[{index}]",
                maximum=_MAX_CLAIM_CHARS,
            )
            sources = global_sources
        elif isinstance(item, Mapping):
            claim = _bounded_string(
                item.get("claim"),
                label=f"buyerInput.claims[{index}].claim",
                maximum=_MAX_CLAIM_CHARS,
            )
            sources = _normalize_sources(item.get("sources", global_sources))
        else:
            raise SellerInputError(
                f"buyerInput.claims[{index}] must be a string or object"
            )
        claims.append((claim, sources))
    return claims


class InitialVerificationExecutor:
    """Seller executor for the declared initial verification/evidence-pack SKUs."""

    def __init__(
        self,
        provider: DecisionProvider | None = None,
        *,
        sku_contracts: Mapping[str, str] | None = None,
    ) -> None:
        self.provider = provider or DeterministicEvidenceDecisionProvider()
        provider_identity(self.provider)
        contracts = dict(_DEFAULT_SKUS if sku_contracts is None else sku_contracts)
        if not contracts or any(kind not in _SKU_KINDS for kind in contracts.values()):
            raise SellerExecutorConfigurationError(
                "verification SKU contracts must map IDs to declared SKU kinds"
            )
        self.sku_contracts = contracts

    def execute(
        self, proposal: Proposal, *, context: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        kind = self.sku_contracts.get(proposal.sku_id)
        if kind is None:
            raise SellerInputError("proposal SKU is not declared for this executor")
        buyer_input = context.get("buyerInput")
        if not isinstance(buyer_input, Mapping):
            raise SellerInputError("context.buyerInput must be a JSON object")
        _finite_json_bytes(buyer_input, label="context.buyerInput")
        decisions = [
            _safe_decision(self.provider, claim, sources)
            for claim, sources in _claims_for_sku(buyer_input, kind)
        ]
        verdicts = [decision["verdict"] for decision in decisions]
        aggregate = verdicts[0] if len(set(verdicts)) == 1 else "abstain"
        all_sources: dict[str, Mapping[str, str]] = {}
        all_evidence: list[Mapping[str, str]] = []
        for decision in decisions:
            for item in decision["evidence"]:
                all_sources[item["sourceId"]] = {
                    "sourceId": item["sourceId"],
                    "url": item["url"],
                    "title": item["title"],
                    "excerpt": item["excerpt"],
                }
                all_evidence.append(item)
        provider_name, model_name = provider_identity(self.provider)
        artifact: dict[str, Any] = {
            "schemaVersion": "autonomerce.seller.verification.v1",
            "artifactType": kind,
            "proposalId": proposal.proposal_id,
            "skuId": proposal.sku_id,
            "verdict": aggregate,
            "verdicts": decisions,
            "claimCount": len(decisions),
            "sources": list(all_sources.values()),
            "evidence": all_evidence,
            "limitations": [_LIMITATION],
            "externalTruthVerified": False,
            "provenance": {
                "evidenceScope": _EVIDENCE_SCOPE,
                "provider": provider_name,
                "model": model_name,
            },
        }
        if len(decisions) == 1:
            artifact["claim"] = decisions[0]["claim"]
        if kind == "evidence-pack":
            artifact["evidencePack"] = {
                "claims": decisions,
                "sources": list(all_sources.values()),
            }
        return artifact


_SENSITIVE_KEYS = frozenset(
    {
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
    }
)


def _normalized_key(value: Any) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _reject_credentials(value: Any, *, path: str = "buyerInput") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = _normalized_key(key)
            if normalized in _SENSITIVE_KEYS or normalized.endswith("token"):
                raise SellerInputError(f"{path} contains a credential-like field")
            _reject_credentials(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_credentials(nested, path=f"{path}[{index}]")


def _canonical_https_url(value: str) -> tuple[str, SplitResult]:
    if not isinstance(value, str) or not value.strip():
        raise SellerExecutorConfigurationError("seller A2A URL is required")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise SellerExecutorConfigurationError(
            "seller A2A URL must be HTTPS without credentials, query, or fragment"
        )
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise SellerExecutorConfigurationError("seller A2A URL has an invalid port") from exc
    if port != 443:
        raise SellerExecutorConfigurationError("seller A2A URL must use port 443")
    host = parsed.hostname.rstrip(".").casefold()
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise SellerExecutorConfigurationError("seller A2A host is not public")
    host_text = f"[{host}]" if ":" in host else host
    path = parsed.path or "/"
    canonical = urlunsplit(("https", host_text, path, "", ""))
    return canonical, urlsplit(canonical)


def _public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError as exc:
        raise SellerTransportError("resolver returned an invalid IP address") from exc
    if not address.is_global:
        raise SellerTransportError("seller A2A host resolved to a non-public IP")
    return address.compressed


def default_public_resolver(host: str, port: int) -> Sequence[str]:
    try:
        records = socket.getaddrinfo(
            host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise SellerTransportError("seller A2A DNS resolution failed") from exc
    return tuple(record[4][0] for record in records)


@dataclass(frozen=True)
class A2AJsonRequest:
    url: str
    body: bytes
    headers: Mapping[str, str]
    timeout_seconds: float
    max_response_bytes: int
    resolved_ips: tuple[str, ...]


@dataclass(frozen=True)
class A2AJsonResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class A2ATransport(Protocol):
    def __call__(self, request: A2AJsonRequest) -> A2AJsonResponse: ...


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self, host: str, port: int, *, pinned_ip: str, timeout: float
    ) -> None:
        super().__init__(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        if self._tunnel_host:
            raise SellerTransportError("HTTP proxy tunnels are not supported")
        raw = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class StdlibPinnedHttpsTransport:
    """Minimal HTTPS POST transport with no redirect or credential machinery."""

    def __call__(self, request: A2AJsonRequest) -> A2AJsonResponse:
        parsed = urlsplit(request.url)
        deadline = time.monotonic() + request.timeout_seconds
        last_error: BaseException | None = None
        for address in request.resolved_ips:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            connection = _PinnedHTTPSConnection(
                parsed.hostname or "",
                parsed.port or 443,
                pinned_ip=address,
                timeout=remaining,
            )
            try:
                path = parsed.path or "/"
                connection.request(
                    "POST", path, body=request.body, headers=dict(request.headers)
                )
                if connection.sock is not None:
                    connection.sock.settimeout(max(0.001, deadline - time.monotonic()))
                response = connection.getresponse()
                length = response.getheader("Content-Length")
                if length is not None and int(length) > request.max_response_bytes:
                    raise SellerTransportError("seller A2A response exceeds size limit")
                body = response.read(request.max_response_bytes + 1)
                if len(body) > request.max_response_bytes:
                    raise SellerTransportError("seller A2A response exceeds size limit")
                return A2AJsonResponse(
                    status_code=response.status,
                    headers={key: value for key, value in response.getheaders()},
                    body=body,
                )
            except SellerTransportError:
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                last_error = exc
            finally:
                connection.close()
        raise SellerTransportError("seller A2A HTTPS request failed") from last_error


def _call_resolver(
    resolver: Callable[..., Sequence[str]], host: str, port: int
) -> Sequence[str]:
    try:
        parameters = inspect.signature(resolver).parameters
    except (TypeError, ValueError):
        return resolver(host, port)
    if len(parameters) == 1:
        return resolver(host)
    return resolver(host, port)


def _json_media_type(headers: Mapping[str, str]) -> bool:
    content_type = ""
    for key, value in headers.items():
        if str(key).casefold() == "content-type":
            content_type = str(value).split(";", 1)[0].strip().casefold()
            break
    return content_type == "application/json" or (
        content_type.startswith("application/") and content_type.endswith("+json")
    )


def _decode_json_object(body: bytes) -> dict[str, Any]:
    try:
        text = body.decode("utf-8")
        value = json.loads(
            text,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SellerTransportError("seller A2A response is not strict UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise SellerTransportError("seller A2A response must be a JSON object")
    return dict(value)


def _extract_artifact(
    response: Mapping[str, Any], proposal: Proposal
) -> Mapping[str, Any]:
    if "jsonrpc" in response:
        if response.get("jsonrpc") != "2.0" or response.get("id") != proposal.proposal_id:
            raise SellerTransportError("seller A2A response does not match the request")
        if "error" in response:
            raise SellerTransportError("seller A2A returned a JSON-RPC error")
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise SellerTransportError("seller A2A result must be a JSON object")
        artifact = result.get("artifact")
        if artifact is None:
            artifacts = result.get("artifacts")
            if isinstance(artifacts, list) and len(artifacts) == 1:
                parts = artifacts[0].get("parts") if isinstance(artifacts[0], Mapping) else None
                if isinstance(parts, list):
                    data_parts = [
                        part.get("data")
                        for part in parts
                        if isinstance(part, Mapping)
                        and part.get("kind") == "data"
                        and isinstance(part.get("data"), Mapping)
                    ]
                    artifact = data_parts[0] if len(data_parts) == 1 else None
    else:
        if (
            response.get("proposalId") != proposal.proposal_id
            or response.get("skuId") != proposal.sku_id
        ):
            raise SellerTransportError("seller A2A response does not match the proposal")
        artifact = response.get("artifact")
    if not isinstance(artifact, Mapping):
        raise SellerTransportError("seller A2A artifact must be a JSON object")
    _finite_json_bytes(artifact, label="seller A2A artifact")
    _reject_credentials(artifact, path="seller A2A artifact")
    return dict(artifact)


class HttpsA2AJsonExecutor:
    """POST one typed A2A request to an exact owner-allowlisted public endpoint."""

    def __init__(
        self,
        *,
        allowed_urls: Sequence[str],
        resolver: Callable[..., Sequence[str]] = default_public_resolver,
        transport: A2ATransport | None = None,
        timeout_seconds: float = 5.0,
        max_request_bytes: int = 65_536,
        max_response_bytes: int = 524_288,
    ) -> None:
        if not allowed_urls:
            raise SellerExecutorConfigurationError(
                "seller A2A exact URL allowlist is required"
            )
        self.allowed_urls = frozenset(
            _canonical_https_url(value)[0] for value in allowed_urls
        )
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
            raise SellerExecutorConfigurationError(
                "seller A2A timeout must be between 0 and 30 seconds"
            )
        if not 1 <= max_request_bytes <= 1_048_576:
            raise SellerExecutorConfigurationError(
                "seller A2A request limit must be between 1 and 1048576 bytes"
            )
        if not 1 <= max_response_bytes <= 5_242_880:
            raise SellerExecutorConfigurationError(
                "seller A2A response limit must be between 1 and 5242880 bytes"
            )
        self.resolver = resolver
        self.transport = transport or StdlibPinnedHttpsTransport()
        self.timeout_seconds = float(timeout_seconds)
        self.max_request_bytes = int(max_request_bytes)
        self.max_response_bytes = int(max_response_bytes)

    def execute(
        self, proposal: Proposal, *, context: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        url, parsed = _canonical_https_url(proposal.seller_agent_url)
        if url not in self.allowed_urls:
            raise SellerTransportError(
                "seller A2A URL is not in the exact owner allowlist"
            )
        buyer_input = context.get("buyerInput")
        if not isinstance(buyer_input, Mapping):
            raise SellerInputError("context.buyerInput must be a JSON object")
        _reject_credentials(buyer_input)
        envelope = {
            "jsonrpc": "2.0",
            "id": proposal.proposal_id,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": f"fulfill-{proposal.proposal_id}",
                    "role": "user",
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "task": "fulfill-paid-proposal",
                                "proposal": {
                                    "proposalId": proposal.proposal_id,
                                    "skuId": proposal.sku_id,
                                    "offeredOutcome": proposal.offered_outcome,
                                    "acceptanceCriteria": list(
                                        proposal.acceptance_criteria
                                    ),
                                },
                                "buyerInput": dict(buyer_input),
                            },
                        }
                    ],
                }
            },
        }
        body = _finite_json_bytes(envelope, label="seller A2A request")
        if len(body) > self.max_request_bytes:
            raise SellerInputError("seller A2A request exceeds size limit")
        host = parsed.hostname or ""
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            resolved = _call_resolver(self.resolver, host, parsed.port or 443)
        else:
            resolved = (literal.compressed,)
        if not resolved:
            raise SellerTransportError("seller A2A host resolved to no addresses")
        public_ips = tuple(dict.fromkeys(_public_ip(value) for value in resolved))
        response = self.transport(
            A2AJsonRequest(
                url=url,
                body=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "autonomerce-seller-executor/1",
                },
                timeout_seconds=self.timeout_seconds,
                max_response_bytes=self.max_response_bytes,
                resolved_ips=public_ips,
            )
        )
        if not isinstance(response, A2AJsonResponse):
            raise SellerTransportError(
                "seller A2A transport returned an invalid response"
            )
        if 300 <= response.status_code < 400:
            raise SellerTransportError("seller A2A redirects are disabled")
        if not 200 <= response.status_code < 300:
            raise SellerTransportError("seller A2A returned a non-success status")
        if len(response.body) > self.max_response_bytes:
            raise SellerTransportError("seller A2A response exceeds size limit")
        if not _json_media_type(response.headers):
            raise SellerTransportError(
                "seller A2A response must use a JSON media type"
            )
        return _extract_artifact(_decode_json_object(response.body), proposal)


def _environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    return dict(os.environ if environment is None else environment)


def _verification_skus(environment: Mapping[str, str]) -> Mapping[str, str]:
    raw = str(
        environment.get("AUTONOMERCE_SELLER_VERIFICATION_SKUS_JSON", "")
    ).strip()
    if not raw:
        return _DEFAULT_SKUS
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SellerExecutorConfigurationError(
            "AUTONOMERCE_SELLER_VERIFICATION_SKUS_JSON must be valid JSON"
        ) from exc
    if not isinstance(value, Mapping) or not value:
        raise SellerExecutorConfigurationError(
            "verification SKU configuration must be a non-empty JSON object"
        )
    contracts = {
        str(sku_id).strip(): str(kind).strip()
        for sku_id, kind in value.items()
        if str(sku_id).strip()
    }
    if len(contracts) != len(value) or any(
        kind not in _SKU_KINDS for kind in contracts.values()
    ):
        raise SellerExecutorConfigurationError(
            "verification SKU configuration contains an unknown SKU kind"
        )
    return contracts


def build_initial_verification_executor(
    environment: Mapping[str, str] | None = None,
    *,
    provider: DecisionProvider | None = None,
) -> InitialVerificationExecutor:
    """Factory path: autonomerce.sales.executors:build_initial_verification_executor."""

    env = _environment(environment)
    return InitialVerificationExecutor(
        provider=provider, sku_contracts=_verification_skus(env)
    )


def _positive_number(
    environment: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = str(environment.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SellerExecutorConfigurationError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise SellerExecutorConfigurationError(f"{name} must be positive")
    return value


def build_https_a2a_executor(
    environment: Mapping[str, str] | None = None,
    *,
    resolver: Callable[..., Sequence[str]] = default_public_resolver,
    transport: A2ATransport | None = None,
) -> HttpsA2AJsonExecutor:
    """Factory path: autonomerce.sales.executors:build_https_a2a_executor."""

    env = _environment(environment)
    raw_urls = str(
        env.get("AUTONOMERCE_SELLER_A2A_ALLOWED_URLS_JSON", "")
    ).strip()
    if not raw_urls:
        raise SellerExecutorConfigurationError(
            "AUTONOMERCE_SELLER_A2A_ALLOWED_URLS_JSON is required"
        )
    try:
        allowed_urls = json.loads(raw_urls)
    except json.JSONDecodeError as exc:
        raise SellerExecutorConfigurationError(
            "AUTONOMERCE_SELLER_A2A_ALLOWED_URLS_JSON must be valid JSON"
        ) from exc
    if not isinstance(allowed_urls, list) or not all(
        isinstance(value, str) for value in allowed_urls
    ):
        raise SellerExecutorConfigurationError(
            "seller A2A allowlist must be a JSON array of strings"
        )
    return HttpsA2AJsonExecutor(
        allowed_urls=allowed_urls,
        resolver=resolver,
        transport=transport,
        timeout_seconds=_positive_number(
            env, "AUTONOMERCE_SELLER_A2A_TIMEOUT_SECONDS", 5.0
        ),
        max_request_bytes=int(
            _positive_number(
                env, "AUTONOMERCE_SELLER_A2A_MAX_REQUEST_BYTES", 65_536
            )
        ),
        max_response_bytes=int(
            _positive_number(
                env, "AUTONOMERCE_SELLER_A2A_MAX_RESPONSE_BYTES", 524_288
            )
        ),
    )


def build_seller_executor(
    environment: Mapping[str, str] | None = None,
    *,
    provider: DecisionProvider | None = None,
    resolver: Callable[..., Sequence[str]] = default_public_resolver,
    transport: A2ATransport | None = None,
) -> InitialVerificationExecutor | HttpsA2AJsonExecutor:
    """Explicit dispatcher suitable for AUTONOMERCE_SELLER_EXECUTOR_FACTORY."""

    env = _environment(environment)
    kind = str(env.get("AUTONOMERCE_SELLER_EXECUTOR_KIND", "")).strip().lower()
    if kind == "verification":
        return build_initial_verification_executor(env, provider=provider)
    if kind in {"https-a2a", "a2a"}:
        return build_https_a2a_executor(
            env, resolver=resolver, transport=transport
        )
    raise SellerExecutorConfigurationError(
        "AUTONOMERCE_SELLER_EXECUTOR_KIND must be verification or https-a2a"
    )


__all__ = [
    "A2AJsonRequest",
    "A2AJsonResponse",
    "A2ATransport",
    "DeterministicEvidenceDecisionProvider",
    "HttpsA2AJsonExecutor",
    "INITIAL_VERIFICATION_SKU_OUTPUT_SCHEMAS",
    "InitialVerificationExecutor",
    "SellerExecutorConfigurationError",
    "SellerExecutorError",
    "SellerInputError",
    "SellerTransportError",
    "StdlibPinnedHttpsTransport",
    "build_https_a2a_executor",
    "build_initial_verification_executor",
    "build_seller_executor",
    "default_public_resolver",
]
