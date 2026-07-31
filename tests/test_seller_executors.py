from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.contracts import Proposal, ProposalState  # noqa: E402
from autonomerce.sales.executors import (  # noqa: E402
    A2AJsonResponse,
    HttpsA2AJsonExecutor,
    InitialVerificationExecutor,
    SellerExecutorConfigurationError,
    SellerInputError,
    SellerTransportError,
    build_https_a2a_executor,
    build_seller_executor,
)


def proposal(
    sku_id: str = "verify-one-claim",
    seller_url: str = "https://seller.example/a2a",
) -> Proposal:
    return Proposal(
        proposal_id="proposal_seller_executor",
        seller_agent_url=seller_url,
        buyer_agent_url="https://buyer.example/a2a",
        sku_id=sku_id,
        problem_observed="A claim needs verification.",
        offered_outcome="Return a sourced verdict.",
        price_usdc=Decimal("0.1"),
        delivery_seconds=120,
        acceptance_criteria=("required_field:verdict",),
        state=ProposalState.PAID,
    )


def source(stance: str = "support") -> dict[str, str]:
    return {
        "sourceId": "source-1",
        "url": "https://evidence.example/report",
        "title": "Supplied report",
        "excerpt": "The supplied report contains evidence relevant to the claim.",
        "stance": stance,
    }


def test_builtin_executor_scopes_non_abstain_verdict_to_cited_evidence():
    artifact = InitialVerificationExecutor().execute(
        proposal(),
        context={
            "buyerInput": {
                "claim": "The API supports structured output.",
                "sources": [source("support")],
            }
        },
    )

    assert artifact["skuId"] == "verify-one-claim"
    assert artifact["verdict"] == "support"
    assert artifact["evidence"][0]["sourceId"] == "source-1"
    assert artifact["externalTruthVerified"] is False
    assert artifact["provenance"]["evidenceScope"] == "buyer_supplied_sources_only"


def test_builtin_executor_abstains_without_usable_evidence_and_rejects_unknown_sku():
    artifact = InitialVerificationExecutor().execute(
        proposal(),
        context={"buyerInput": {"claim": "An unsupported claim.", "sources": []}},
    )
    assert artifact["verdict"] == "abstain"
    assert artifact["evidence"] == []

    with pytest.raises(SellerInputError, match="not declared"):
        InitialVerificationExecutor().execute(
            proposal("unknown-sku"),
            context={"buyerInput": {"claim": "Claim", "sources": []}},
        )


def test_batch_and_evidence_pack_shapes_match_the_declared_sku():
    batch = InitialVerificationExecutor().execute(
        proposal("verify-five-claims"),
        context={
            "buyerInput": {
                "claims": ["Claim one", "Claim two"],
                "sources": [source()],
            }
        },
    )
    assert batch["artifactType"] == "verify-five-claims"
    assert batch["claimCount"] == 2
    assert len(batch["verdicts"]) == 2

    pack = InitialVerificationExecutor().execute(
        proposal("evidence-pack"),
        context={"buyerInput": {"claim": "Claim", "sources": [source()]}},
    )
    assert pack["artifactType"] == "evidence-pack"
    assert pack["evidencePack"]["sources"][0]["sourceId"] == "source-1"


class RecordingTransport:
    def __init__(self, response: A2AJsonResponse) -> None:
        self.response = response
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.response


def json_response(payload, *, status=200, content_type="application/json"):
    return A2AJsonResponse(
        status_code=status,
        headers={"Content-Type": content_type},
        body=json.dumps(payload).encode(),
    )


def test_https_executor_uses_exact_allowlist_public_dns_and_credential_free_body():
    transport = RecordingTransport(
        json_response(
            {
                "jsonrpc": "2.0",
                "id": "proposal_seller_executor",
                "result": {"artifact": {"verdict": "abstain"}},
            }
        )
    )
    executor = HttpsA2AJsonExecutor(
        allowed_urls=["https://seller.example/a2a"],
        resolver=lambda host, port: ["93.184.216.34"],
        transport=transport,
    )

    artifact = executor.execute(
        proposal(),
        context={
            "buyerInput": {"claim": "Claim", "sources": []},
            "payment_id": "must-not-be-forwarded",
        },
    )

    assert artifact == {"verdict": "abstain"}
    request = transport.requests[0]
    payload = json.loads(request.body)
    serialized = json.dumps(payload).lower()
    assert "payment_id" not in serialized
    assert "authorization" not in {
        key.lower() for key in request.headers
    }
    assert request.resolved_ips == ("93.184.216.34",)


def test_https_executor_rejects_private_dns_suffix_attacks_credentials_and_redirects():
    transport = RecordingTransport(
        json_response(
            {
                "jsonrpc": "2.0",
                "id": "proposal_seller_executor",
                "result": {"artifact": {"verdict": "abstain"}},
            }
        )
    )
    private = HttpsA2AJsonExecutor(
        allowed_urls=["https://seller.example/a2a"],
        resolver=lambda host, port: ["10.0.0.8"],
        transport=transport,
    )
    with pytest.raises(SellerTransportError, match="non-public"):
        private.execute(
            proposal(),
            context={"buyerInput": {"claim": "Claim", "sources": []}},
        )
    assert transport.requests == []

    public = HttpsA2AJsonExecutor(
        allowed_urls=["https://seller.example/a2a"],
        resolver=lambda host, port: ["93.184.216.34"],
        transport=transport,
    )
    with pytest.raises(SellerTransportError, match="allowlist"):
        public.execute(
            proposal(seller_url="https://seller.example.evil/a2a"),
            context={"buyerInput": {"claim": "Claim", "sources": []}},
        )
    with pytest.raises(SellerInputError, match="credential-like"):
        public.execute(
            proposal(),
            context={"buyerInput": {"claim": "Claim", "apiToken": "secret"}},
        )

    redirect = HttpsA2AJsonExecutor(
        allowed_urls=["https://seller.example/a2a"],
        resolver=lambda host, port: ["93.184.216.34"],
        transport=RecordingTransport(
            A2AJsonResponse(302, {"Location": "https://evil.example"}, b"")
        ),
    )
    with pytest.raises(SellerTransportError, match="redirects"):
        redirect.execute(
            proposal(),
            context={"buyerInput": {"claim": "Claim", "sources": []}},
        )


def test_factories_fail_closed_and_are_loadable_by_adapter_factory_path():
    with pytest.raises(SellerExecutorConfigurationError, match="KIND"):
        build_seller_executor(environment={})
    with pytest.raises(SellerExecutorConfigurationError, match="ALLOWED_URLS"):
        build_https_a2a_executor(environment={})

    executor = build_seller_executor(
        environment={"AUTONOMERCE_SELLER_EXECUTOR_KIND": "verification"}
    )
    assert isinstance(executor, InitialVerificationExecutor)
