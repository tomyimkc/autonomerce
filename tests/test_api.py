from pathlib import Path
import sys

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.api import AdapterBundle, InMemoryRepository, create_app  # noqa: E402
from autonomerce.api.app import _accepted_payer_wallet  # noqa: E402


def _client() -> TestClient:
    return TestClient(create_app())


def _onboard_flow(
    client: TestClient, *, output_schema: dict | None = None
) -> dict[str, str]:
    seller_response = client.post(
        "/sellers",
        json={
            "name": "Evidence Seller",
            "agentCardUrl": "https://seller.example/.well-known/agent-card.json",
            "network": "ARC-TESTNET",
        },
    )
    assert seller_response.status_code == 201, seller_response.text
    seller_id = seller_response.json()["sellerId"]

    capability_response = client.post(
        f"/sellers/{seller_id}/capabilities",
        json={
            "name": "Source verification",
            "description": "Return a cited support or abstain verdict",
            "inputSchema": {"type": "object"},
            "outputSchema": output_schema
            or {
                "type": "object",
                "required": ["verdict"],
                "properties": {"verdict": {"type": "string"}},
            },
            "tags": ["verification"],
        },
    )
    assert capability_response.status_code == 201, capability_response.text
    capability_id = capability_response.json()["capabilityId"]

    sku_response = client.post(
        f"/sellers/{seller_id}/skus/preview",
        json={
            "capabilityIds": [capability_id],
            "basePriceUsdc": "1",
            "maximumLatencySeconds": 120,
            "capacityPerHour": 20,
        },
    )
    assert sku_response.status_code == 200, sku_response.text
    sku_id = sku_response.json()["skus"][0]["skuId"]

    policy_response = client.post(
        f"/sellers/{seller_id}/policies",
        json={
            "minimumPriceUsdc": "0.8",
            "maximumPriceUsdc": "5",
            "maximumDiscountFraction": "0.2",
            "allowedBuyerHosts": ["buyer.example"],
            "allowedChains": ["ARC-TESTNET"],
            "allowedToken": "USDC",
            "unattended": True,
        },
    )
    assert policy_response.status_code == 201, policy_response.text

    prospect_response = client.post(
        "/prospects",
        json={
            "buyerAgentUrl": "https://buyer.example/.well-known/agent-card.json",
            "desiredOutcome": "Verify one claim",
            "maximumPriceUsdc": "2",
            "requiredTags": ["verification"],
            "optedIn": True,
            "consentReference": "consent:test-buyer:verification:v1",
        },
    )
    assert prospect_response.status_code == 201, prospect_response.text
    need_id = prospect_response.json()["needId"]

    return {
        "seller_id": seller_id,
        "sku_id": sku_id,
        "need_id": need_id,
    }


def test_health_and_openapi_are_available_without_credentials():
    with _client() as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["storage"] == "memory"
        assert health.json()["authenticationRequired"] is False
        assert health.json()["paymentMode"] == "offline"
        assert health.json()["movesFunds"] is False
        assert client.get("/openapi.json").status_code == 200


def test_complete_offline_commerce_flow_and_public_receipt_redaction():
    with _client() as client:
        ids = _onboard_flow(client)

        proposal_response = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
                "problemObserved": "A claim needs source verification",
                "priceUsdc": "1",
                "deliverySeconds": 120,
            },
        )
        assert proposal_response.status_code == 201, proposal_response.text
        proposal = proposal_response.json()
        proposal_id = proposal["proposalId"]
        assert proposal_id.startswith("proposal_")
        assert proposal["state"] == "offered"

        listed = client.get("/proposals").json()
        assert listed["count"] == 1
        assert listed["proposals"][0]["proposalId"] == proposal_id

        counter_response = client.post(
            f"/proposals/{proposal_id}/counter",
            json={"priceUsdc": "0.9"},
        )
        assert counter_response.status_code == 200, counter_response.text
        assert counter_response.json()["accepted"] is True
        assert counter_response.json()["proposal"]["revision"] == 2

        accept_response = client.post(f"/proposals/{proposal_id}/accept")
        assert accept_response.status_code == 200, accept_response.text
        assert accept_response.json()["proposal"]["state"] == "accepted"

        payment_response = client.post(
            f"/proposals/{proposal_id}/pay",
                json={
                    "idempotencyKey": "order-001",
                    "chain": "ARC-TESTNET",
                    "publicReceipt": False,
                },
        )
        assert payment_response.status_code == 200, payment_response.text
        payment = payment_response.json()
        assert payment["paymentId"].startswith("payment_")
        assert payment["state"] == "confirmed"
        assert payment["mocked"] is True
        assert "payerWallet" not in payment
        assert "payeeWallet" not in payment

        replay = client.post(
            f"/proposals/{proposal_id}/pay",
            json={"idempotencyKey": "order-001"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["paymentId"] == payment["paymentId"]
        assert replay.json()["idempotentReplay"] is True

        fulfillment_response = client.post(
            f"/proposals/{proposal_id}/fulfill",
            json={"artifact": {"verdict": "abstain", "sources": []}},
        )
        assert fulfillment_response.status_code == 200, fulfillment_response.text
        fulfillment = fulfillment_response.json()
        assert fulfillment["fulfillmentId"].startswith("fulfillment_")
        assert fulfillment["accepted"] is True
        assert "artifact" not in fulfillment
        assert fulfillment["artifactMetadata"]["contentType"] == "application/json"

        assert client.get(f"/receipts/{proposal_id}").status_code == 404
        reused_contact_consent = client.post(
            f"/receipts/{proposal_id}/publish",
            json={"consentReference": "consent:test-buyer:verification:v1"},
        )
        assert reused_contact_consent.status_code == 409
        aliased_contact_consent = client.post(
            f"/receipts/{proposal_id}/publish",
            json={
                "consentReference": (
                    "consent:test-buyer:verification:v1#publication"
                )
            },
        )
        assert aliased_contact_consent.status_code == 409
        publication = client.post(
            f"/receipts/{proposal_id}/publish",
            json={"consentReference": "publication:order-001:v1"},
        )
        assert publication.status_code == 200, publication.text
        receipt_response = client.get(
            f"/receipts/{publication.json()['receiptId']}"
        )
        assert receipt_response.status_code == 200
        receipt = receipt_response.json()
        assert receipt["proposalId"] == proposal_id
        assert receipt["acceptanceVerdict"] == "accepted"
        assert receipt["anonymizedOrderId"].startswith("order_")
        serialized = receipt_response.text.lower()
        assert "buyer.example" not in serialized
        assert "idempotency" not in serialized
        assert '"verdict"' not in serialized
        assert '"sources"' not in serialized

        metrics = client.get("/metrics").json()
        assert metrics["registeredSellerAgents"] == 1
        assert metrics["activatedSellerAgents"] == 1
        assert metrics["proposalsSent"] == 1
        assert metrics["paidTasks"] is None
        assert metrics["paidTasksStatus"] == (
            "requires_external_customer_classification"
        )
        assert metrics["confirmedLivePayments"] == 0
        assert metrics["mockedPaymentCount"] == 1
        assert metrics["successfulFulfillment"] == 1
        assert metrics["usdcRevenue"] is None
        assert metrics["liveSettlementVolumeUsdc"] == "0"
        assert metrics["mockedPaymentVolumeUsdc"] == "0.9"
        assert metrics["medianDeliverySeconds"] is not None
        assert metrics["grossMarginUsdc"] is None
        assert metrics["grossMarginStatus"] == "requires_measured_variable_costs"
        assert metrics["revenueClassification"] == (
            "unmeasured_external_customer_status"
        )


def test_accepted_settlement_recipient_is_immutable_and_retry_resumes():
    replacement_wallet = "0x9999999999999999999999999999999999999999"
    proposal_payload: dict[str, object]

    with _client() as client:
        ids = _onboard_flow(client)
        proposal_payload = {
            "sellerId": ids["seller_id"],
            "buyerNeedId": ids["need_id"],
            "skuId": ids["sku_id"],
            "problemObserved": "A claim needs immutable settlement",
            "priceUsdc": "1",
            "deliverySeconds": 120,
            "expiresAt": "2030-01-01T00:00:00Z",
        }
        created = client.post("/proposals", json=proposal_payload)
        assert created.status_code == 201, created.text
        proposal_id = created.json()["proposalId"]

        accepted = client.post(f"/proposals/{proposal_id}/accept")
        assert accepted.status_code == 200, accepted.text
        settlement = accepted.json()["settlementAuthorization"]
        original_payee = settlement["payeeWallet"]
        assert original_payee != replacement_wallet

        mutated_seller = client.post(
            "/sellers",
            json={
                "name": "Evidence Seller",
                "agentCardUrl": (
                    "https://seller.example/.well-known/agent-card.json"
                ),
                "network": "ARC-TESTNET",
                "walletAddress": replacement_wallet,
            },
        )
        assert mutated_seller.status_code == 201, mutated_seller.text
        assert mutated_seller.json()["sellerId"] == ids["seller_id"]

        payment = client.post(
            f"/proposals/{proposal_id}/pay",
            json={
                "idempotencyKey": "stable-workflow-payment",
                "chain": settlement["chain"],
                "token": settlement["token"],
            },
        )
        assert payment.status_code == 200, payment.text
        stored_payment = client.app.state.repository.payment_for_proposal(
            proposal_id
        )
        assert stored_payment is not None
        assert stored_payment.payee_wallet == original_payee
        assert stored_payment.payee_wallet != replacement_wallet

        recreated = client.post("/proposals", json=proposal_payload)
        assert recreated.status_code == 201, recreated.text
        assert recreated.json()["state"] == "paid"

        reaccepted = client.post(f"/proposals/{proposal_id}/accept")
        assert reaccepted.status_code == 200, reaccepted.text
        assert reaccepted.json()["proposal"]["state"] == "paid"
        assert (
            reaccepted.json()["settlementAuthorization"]["authorizationId"]
            == settlement["authorizationId"]
        )

        replay = client.post(
            f"/proposals/{proposal_id}/pay",
            json={"idempotencyKey": "stable-workflow-payment"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["paymentId"] == payment.json()["paymentId"]
        assert replay.json()["idempotentReplay"] is True

        fulfillment = client.post(
            f"/proposals/{proposal_id}/fulfill",
            json={"artifact": {"verdict": "abstain"}},
        )
        assert fulfillment.status_code == 200, fulfillment.text


def test_proposals_bind_exact_buyer_need_and_fulfillment_input():
    seen_buyer_inputs: list[dict[str, object]] = []

    class CapturingFulfillment:
        def fulfill(self, proposal, *, artifact, context):
            del proposal, artifact
            seen_buyer_inputs.append(dict(context["buyerInput"]))
            return {"verdict": "abstain"}

    with TestClient(
        create_app(
            adapters=AdapterBundle(fulfillment=CapturingFulfillment())
        )
    ) as client:
        ids = _onboard_flow(client)
        buyer_url = "https://buyer.example/.well-known/agent-card.json"
        needs: list[str] = []
        for suffix in ("first", "second"):
            response = client.post(
                "/prospects",
                json={
                    "buyerAgentUrl": buyer_url,
                    "desiredOutcome": "Verify one claim",
                    "maximumPriceUsdc": "2",
                    "requiredTags": ["verification"],
                    "inputPayload": {"claim": f"{suffix}-private-input"},
                    "optedIn": True,
                    "consentReference": f"consent:{suffix}:v1",
                },
            )
            assert response.status_code == 201, response.text
            needs.append(response.json()["needId"])
        assert needs[0] != needs[1]

        proposal_ids: list[str] = []
        for need_id in needs:
            response = client.post(
                "/proposals",
                json={
                    "sellerId": ids["seller_id"],
                    "buyerNeedId": need_id,
                    "skuId": ids["sku_id"],
                    "problemObserved": "A supplied claim needs verification",
                    "priceUsdc": "1",
                    "deliverySeconds": 120,
                },
            )
            assert response.status_code == 201, response.text
            assert response.json()["buyerNeedId"] == need_id
            proposal_ids.append(response.json()["proposalId"])
        assert proposal_ids[0] != proposal_ids[1]

        second_id = proposal_ids[1]
        accepted = client.post(f"/proposals/{second_id}/accept")
        assert accepted.status_code == 200, accepted.text
        payment = client.post(
            f"/proposals/{second_id}/pay",
            json={"idempotencyKey": "need-bound-payment"},
        )
        assert payment.status_code == 200, payment.text
        fulfillment = client.post(f"/proposals/{second_id}/fulfill", json={})
        assert fulfillment.status_code == 200, fulfillment.text
        assert seen_buyer_inputs == [{"claim": "second-private-input"}]


def test_acceptance_uses_the_owner_allowlisted_payer_wallet():
    real_payer = "0x9999999999999999999999999999999999999999"
    payment_adapter = AdapterBundle().payment
    payment_adapter.allowed_payer_wallets = (real_payer,)

    with TestClient(
        create_app(adapters=AdapterBundle(payment=payment_adapter))
    ) as client:
        ids = _onboard_flow(client)
        proposal = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
                "problemObserved": "Use the configured Circle payer",
                "priceUsdc": "1",
                "deliverySeconds": 120,
            },
        )
        assert proposal.status_code == 201, proposal.text
        proposal_id = proposal.json()["proposalId"]
        accepted = client.post(f"/proposals/{proposal_id}/accept")
        assert accepted.status_code == 200, accepted.text
        assert (
            accepted.json()["settlementAuthorization"]["payerWallet"]
            == real_payer
        )

        paid = client.post(
            f"/proposals/{proposal_id}/pay",
            json={"idempotencyKey": "configured-payer-payment"},
        )
        assert paid.status_code == 200, paid.text
        stored = client.app.state.repository.payment_for_proposal(proposal_id)
        assert stored is not None
        assert stored.payer_wallet == real_payer


def test_live_acceptance_rejects_explicit_payer_without_adapter_allowlist():
    class UnconfiguredLivePayment:
        allowed_payer_wallets: tuple[str, ...] = ()

    with pytest.raises(
        HTTPException,
        match="owner-configured payer allowlist",
    ):
        _accepted_payer_wallet(
            UnconfiguredLivePayment(),
            chain="ARC-TESTNET",
            requested_payer_wallet=(
                "0x9999999999999999999999999999999999999999"
            ),
            non_offline=True,
            offline_identifier="unused",
        )


def test_policy_fails_closed_for_non_opted_in_and_out_of_bounds_offers():
    with _client() as client:
        rejected = client.post(
            "/prospects",
            json={
                "buyerAgentUrl": "https://buyer.example/agent",
                "desiredOutcome": "Verify one claim",
                "maximumPriceUsdc": "2",
                "optedIn": False,
            },
        )
        assert rejected.status_code == 403

        ids = _onboard_flow(client)
        proposal = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
                "priceUsdc": "0.79",
            },
        )
        assert proposal.status_code == 403
        assert "policy" in proposal.json()["detail"]
        assert client.get("/metrics").json()["policyDenials"] == 2


def test_one_proposal_cannot_settle_twice_with_different_keys():
    with _client() as client:
        ids = _onboard_flow(client)
        proposal = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
            },
        ).json()
        proposal_id = proposal["proposalId"]
        assert client.post(f"/proposals/{proposal_id}/accept").status_code == 200
        assert (
            client.post(
                f"/proposals/{proposal_id}/pay",
                json={"idempotencyKey": "first-key"},
            ).status_code
            == 200
        )
        duplicate = client.post(
            f"/proposals/{proposal_id}/pay",
            json={"idempotencyKey": "second-key"},
        )
        assert duplicate.status_code == 409
        assert client.get("/metrics").json()["duplicatePaymentCount"] == 1


def test_fulfillment_fails_closed_when_output_contract_is_not_satisfied():
    with _client() as client:
        ids = _onboard_flow(client)
        proposal_id = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
            },
        ).json()["proposalId"]
        assert client.post(f"/proposals/{proposal_id}/accept").status_code == 200
        assert (
            client.post(
                f"/proposals/{proposal_id}/pay",
                json={"idempotencyKey": "invalid-delivery"},
            ).status_code
            == 200
        )

        fulfillment = client.post(
            f"/proposals/{proposal_id}/fulfill",
            json={"artifact": {"sources": []}},
        )
        assert fulfillment.status_code == 200, fulfillment.text
        assert fulfillment.json()["accepted"] is False
        assert (
            fulfillment.json()["acceptanceResults"]["$schema.required.verdict"]
            is False
        )
        assert client.get(f"/receipts/{proposal_id}").status_code == 404
        assert (
            client.post(
                f"/receipts/{proposal_id}/publish",
                json={"consentReference": "publication:invalid-delivery:v1"},
            ).status_code
            == 200
        )
        receipt = client.get(f"/receipts/{proposal_id}").json()
        assert receipt["acceptanceVerdict"] == "rejected"
        assert client.get("/metrics").json()["successfulFulfillment"] == 0


@pytest.mark.parametrize(
    "secret_key",
    [
        "api_key",
        "api-key",
        "apiKey",
        "ApiKey",
        "client_secret",
        "client-secret",
        "clientSecret",
        "session_token",
        "session-token",
        "sessionToken",
    ],
)
def test_secret_bearing_manifest_fields_are_rejected(secret_key: str):
    with _client() as client:
        response = client.post(
            "/sellers",
            json={
                "name": "Unsafe seller",
                "agentUrl": "https://seller.example/agent",
                "manifest": {secret_key: "must-not-enter-storage"},
            },
        )
        assert response.status_code == 400
        assert "secret-bearing field" in response.json()["detail"]


def test_private_routes_require_bearer_auth_and_reject_cross_tenant_owner():
    headers = {"Authorization": "Bearer owner-token"}
    repository = InMemoryRepository()
    repository.save_seller(
        {
            "seller_id": "seller_foreign",
            "name": "Foreign seller",
            "agent_url": "https://foreign.example/agent",
            "source_kind": "a2a",
            "manifest": {},
            "wallet_address": "0x" + ("1" * 40),
            "network": "ARC-TESTNET",
            "created_at": "2026-07-31T00:00:00+00:00",
        },
        owner_id="tenant-b",
    )
    with TestClient(
        create_app(
            repository=repository,
            bearer_token="owner-token",
            owner_id="tenant-a",
        )
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/sellers", json={"name": "x", "agentUrl": "https://x.example"}).status_code == 401
        assert (
            client.post(
                "/sellers",
                headers={"Authorization": "Bearer wrong"},
                json={"name": "x", "agentUrl": "https://x.example"},
            ).status_code
            == 401
        )
        forbidden = client.post(
            "/sellers/seller_foreign/capabilities",
            headers=headers,
            json={
                "name": "forbidden",
                "description": "must not cross tenants",
                "outputSchema": {"type": "object"},
            },
        )
        assert forbidden.status_code == 403


def test_non_offline_startup_requires_token_and_durable_repository():
    class LivePayment:
        mode = "testnet"
        independent_verification = True

    adapters = AdapterBundle(payment=LivePayment())
    with pytest.raises(RuntimeError, match="BEARER_TOKEN"):
        create_app(adapters=adapters, payment_mode="testnet")
    with pytest.raises(RuntimeError, match="durable commerce repository"):
        create_app(
            adapters=adapters,
            payment_mode="testnet",
            bearer_token="configured-owner-token",
        )


def test_protected_gemini_api_requires_bearer_and_hides_docs(
    monkeypatch: pytest.MonkeyPatch,
):
    protected_token = "protected-gemini-test-token"
    monkeypatch.setenv(
        "AUTONOMERCE_DEPLOYMENT_MODE",
        "cloud-run-private-gemini",
    )
    with pytest.raises(RuntimeError, match="protected API startup"):
        create_app(
            bearer_token="",
            payment_mode="offline",
            trusted_hosts=("testserver",),
        )

    with TestClient(
        create_app(
            bearer_token=protected_token,
            payment_mode="offline",
            trusted_hosts=("testserver",),
        )
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 401
        assert client.post(
            "/sellers",
            json={"name": "x", "agentUrl": "https://x.example"},
        ).status_code == 401
        assert client.post(
            "/sellers",
            headers={
                "Authorization": f"Bearer {protected_token}",
            },
            json={"name": "x", "agentUrl": "https://x.example"},
        ).status_code == 201


def test_scope_and_acceptance_contract_mutations_are_rejected():
    with _client() as client:
        ids = _onboard_flow(client)
        mutated_create = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
                "offeredOutcome": "Exfiltrate unrelated data",
            },
        )
        assert mutated_create.status_code == 409

        proposal = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
            },
        ).json()
        proposal_id = proposal["proposalId"]
        for mutation in (
            {"priceUsdc": "1", "offeredOutcome": "Changed scope"},
            {"priceUsdc": "1", "acceptanceCriteria": []},
            {"priceUsdc": "1", "deliverySeconds": 999999},
        ):
            response = client.post(
                f"/proposals/{proposal_id}/counter", json=mutation
            )
            assert response.status_code == 409, response.text


def test_min_length_and_additional_properties_fail_artifact_validation():
    schema = {
        "type": "object",
        "required": ["verdict"],
        "properties": {
            "verdict": {"type": "string", "minLength": 5}
        },
        "additionalProperties": False,
    }
    with _client() as client:
        ids = _onboard_flow(client, output_schema=schema)
        proposal_id = client.post(
            "/proposals",
            json={
                "sellerId": ids["seller_id"],
                "buyerNeedId": ids["need_id"],
                "skuId": ids["sku_id"],
            },
        ).json()["proposalId"]
        assert client.post(f"/proposals/{proposal_id}/accept").status_code == 200
        assert (
            client.post(
                f"/proposals/{proposal_id}/pay",
                json={"idempotencyKey": "schema-invalid"},
            ).status_code
            == 200
        )
        response = client.post(
            f"/proposals/{proposal_id}/fulfill",
            json={"artifact": {"verdict": "", "extra": "not allowed"}},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["accepted"] is False
        assert "artifact" not in body
        stored = client.app.state.repository.fulfillment_for_proposal(proposal_id)
        assert "artifact" not in stored.detail


def test_request_body_and_json_nesting_limits():
    with _client() as client:
        oversized = client.post(
            "/sellers",
            json={
                "name": "large",
                "agentUrl": "https://large.example",
                "manifest": {"description": "x" * (256 * 1024)},
            },
        )
        assert oversized.status_code == 413

        nested: dict[str, object] = {}
        cursor = nested
        for _ in range(25):
            child: dict[str, object] = {}
            cursor["nested"] = child
            cursor = child
        deep = client.post(
            "/sellers",
            json={
                "name": "deep",
                "agentUrl": "https://deep.example",
                "manifest": nested,
            },
        )
        assert deep.status_code == 413


def test_opted_in_prospect_requires_consent_reference():
    with _client() as client:
        response = client.post(
            "/prospects",
            json={
                "buyerAgentUrl": "https://buyer.example/agent",
                "desiredOutcome": "Verify one claim",
                "maximumPriceUsdc": "2",
                "optedIn": True,
            },
        )
        assert response.status_code == 422
