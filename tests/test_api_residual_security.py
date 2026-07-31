import asyncio
import base64
import json
from pathlib import Path
import sys
from typing import Any

import httpx
from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.api import AdapterBundle, create_app  # noqa: E402
from autonomerce.api.rate_limit import (  # noqa: E402
    RateLimitExceeded,
    RateLimitPolicy,
    RequestLimiter,
    RouteBudget,
)
from autonomerce.api.sqlite_repository import SQLiteRepository  # noqa: E402
from autonomerce.sales.agent_cards import (  # noqa: E402
    MAX_AGENT_CARD_BYTES,
    MAX_AGENT_CARD_DEPTH,
    MAX_AGENT_CARD_LIST_ITEMS,
    MAX_AGENT_CARD_NODES,
    MAX_AGENT_CARD_STRING_LENGTH,
    AgentCardError,
    parse_agent_card,
)


def _agent_card() -> dict[str, Any]:
    return {
        "name": "Fixture Agent",
        "description": "A bounded offline fixture",
        "url": "https://buyer.example/a2a",
        "version": "1.0.0",
        "capabilities": {},
        "skills": [
            {
                "id": "verify",
                "name": "Verify",
                "description": "Verify one input",
            }
        ],
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _exact_size_agent_card() -> dict[str, Any]:
    for full_strings in range(MAX_AGENT_CARD_LIST_ITEMS - 1):
        payload = _agent_card()
        padding = ["x" * MAX_AGENT_CARD_STRING_LENGTH] * full_strings + [""]
        payload["capabilities"] = {"padding": padding}
        remaining = MAX_AGENT_CARD_BYTES - len(_canonical_bytes(payload))
        if 0 <= remaining < MAX_AGENT_CARD_STRING_LENGTH:
            padding[-1] = "x" * remaining
            assert len(_canonical_bytes(payload)) == MAX_AGENT_CARD_BYTES
            return payload
    raise AssertionError("could not construct an exact-size Agent Card fixture")


@pytest.mark.parametrize(
    "secret_key",
    [
        "token",
        "accessToken",
        "oauthAccessToken",
        "mySessionToken",
        "backupRefreshToken",
        "clientSigningPrivateKey",
        "privateKeyPem",
        "merchantPrivateKeyPem",
        "serviceClientSecret",
    ],
)
def test_credential_key_variants_are_rejected(secret_key: str):
    with TestClient(create_app()) as client:
        response = client.post(
            "/sellers",
            json={
                "name": "Unsafe seller",
                "agentUrl": "https://seller.example/agent",
                "manifest": {secret_key: "must-not-enter-storage"},
            },
        )
    assert response.status_code == 400
    assert response.json() == {
        "detail": f"secret-bearing field is not accepted: payload.manifest.{secret_key}"
    }


@pytest.mark.parametrize(
    "credential",
    [
        "Bearer abc.def-123",
        "Basic "
        + base64.b64encode(b"fixture-user:fixture-password").decode("ascii"),
        "-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----",  # secret-scan: allow-test-fixture
        "https://fixture-user:fixture-password@seller.example/agent",
    ],
)
def test_inline_credential_values_are_rejected_without_reflection(
    credential: str,
):
    with TestClient(create_app()) as client:
        response = client.post(
            "/sellers",
            json={
                "name": "Unsafe seller",
                "agentUrl": "https://seller.example/agent",
                "manifest": {"description": credential},
            },
        )
    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "credential-bearing value is not accepted: "
            "payload.manifest.description"
        )
    }
    assert credential not in response.text


def test_offline_ingestion_accepts_loopback_fixtures_but_rejects_private_networks():
    with TestClient(create_app()) as client:
        seller = client.post(
            "/sellers",
            json={
                "name": "Local seller",
                "agentUrl": "http://127.0.0.1:8765/agent",
            },
        )
        assert seller.status_code == 201, seller.text

        prospect = client.post(
            "/prospects",
            json={
                "buyerAgentUrl": "http://localhost:8766/agent",
                "desiredOutcome": "Use a local deterministic fixture",
                "maximumPriceUsdc": "1",
                "optedIn": True,
                "consentReference": "consent:local-fixture:v1",
            },
        )
        assert prospect.status_code == 201, prospect.text

        for path, field in (
            ("/sellers", "agentUrl"),
            ("/prospects", "buyerAgentUrl"),
        ):
            payload = (
                {
                    "name": "Private seller",
                    field: "http://192.168.1.10/agent",
                }
                if path == "/sellers"
                else {
                    field: "http://192.168.1.10/agent",
                    "desiredOutcome": "Unsafe network target",
                    "maximumPriceUsdc": "1",
                    "optedIn": True,
                    "consentReference": "consent:private-target:v1",
                }
            )
            rejected = client.post(path, json=payload)
            assert rejected.status_code == 422
            assert "offline fixture URL" in rejected.json()["detail"]


def test_agent_card_mapping_and_serialized_inputs_share_all_limits():
    exact = _exact_size_agent_card()
    assert len(_canonical_bytes(exact)) == MAX_AGENT_CARD_BYTES
    for source in (exact, _canonical_bytes(exact)):
        assert parse_agent_card(source).name == "Fixture Agent"

    oversized = json.loads(_canonical_bytes(exact))
    oversized["capabilities"]["padding"][-1] += "x"
    assert len(_canonical_bytes(oversized)) == MAX_AGENT_CARD_BYTES + 1

    too_deep = _agent_card()
    nested: dict[str, Any] = {}
    cursor = nested
    for _ in range(MAX_AGENT_CARD_DEPTH + 1):
        child: dict[str, Any] = {}
        cursor["nested"] = child
        cursor = child
    too_deep["capabilities"] = nested

    too_many_nodes = _agent_card()
    branch_count = (MAX_AGENT_CARD_NODES // MAX_AGENT_CARD_LIST_ITEMS) + 2
    too_many_nodes["capabilities"] = {
        f"branch{index}": [0] * MAX_AGENT_CARD_LIST_ITEMS
        for index in range(branch_count)
    }

    too_long = _agent_card()
    too_long["description"] = "x" * (MAX_AGENT_CARD_STRING_LENGTH + 1)

    too_many_items = _agent_card()
    too_many_items["defaultInputModes"] = [
        "application/json"
    ] * (MAX_AGENT_CARD_LIST_ITEMS + 1)

    cases = (
        (oversized, "maximum fixture size"),
        (too_deep, "nesting is too deep"),
        (too_many_nodes, "too many values"),
        (too_long, "maximum string length"),
        (too_many_items, "too many items"),
    )
    for payload, message in cases:
        for source in (payload, _canonical_bytes(payload)):
            with pytest.raises(AgentCardError, match=message):
                parse_agent_card(source)


def _budget(
    *,
    requests: int,
    concurrency: int,
    window_seconds: float = 60,
) -> RouteBudget:
    return RouteBudget(
        owner_requests=requests,
        ip_requests=requests,
        window_seconds=window_seconds,
        owner_concurrency=concurrency,
        ip_concurrency=concurrency,
    )


def test_rate_limits_return_deterministic_429_and_expensive_routes_are_stricter():
    limiter = RequestLimiter(
        policy=RateLimitPolicy(
            standard=_budget(requests=2, concurrency=2),
            gemini=_budget(requests=1, concurrency=1),
            payment=_budget(requests=1, concurrency=1),
            fulfillment=_budget(requests=1, concurrency=1),
        )
    )
    with TestClient(create_app(rate_limiter=limiter)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        limited = client.get("/health")
        assert limited.status_code == 429
        assert limited.json() == {"detail": "request rate limit exceeded"}
        assert limited.headers["retry-after"] == "60"

    expensive_limiter = RequestLimiter(
        policy=RateLimitPolicy(
            standard=_budget(requests=10, concurrency=4),
            gemini=_budget(requests=1, concurrency=1),
            payment=_budget(requests=1, concurrency=1),
            fulfillment=_budget(requests=1, concurrency=1),
        )
    )
    with TestClient(create_app(rate_limiter=expensive_limiter)) as client:
        expensive_requests = (
            ("/sellers/missing/skus/preview", {}),
            (
                "/proposals/missing/pay",
                {"idempotencyKey": "payment-missing"},
            ),
            ("/proposals/missing/fulfill", {}),
        )
        for path, payload in expensive_requests:
            first = client.post(path, json=payload)
            assert first.status_code == 404
            second = client.post(path, json=payload)
            assert second.status_code == 429
            assert second.json() == {"detail": "request rate limit exceeded"}


def test_owner_and_direct_ip_rate_budgets_are_independent():
    async def scenario() -> None:
        shared_ip_limiter = RequestLimiter(
            policy=RateLimitPolicy(
                standard=RouteBudget(
                    owner_requests=2,
                    ip_requests=1,
                    window_seconds=60,
                    owner_concurrency=2,
                    ip_concurrency=2,
                )
            )
        )
        lease = await shared_ip_limiter.acquire(
            owner_id="owner-a",
            ip_address="203.0.113.10",
            method="GET",
            path="/health",
        )
        await lease.release()
        with pytest.raises(RateLimitExceeded, match="rate limit"):
            await shared_ip_limiter.acquire(
                owner_id="owner-b",
                ip_address="203.0.113.10",
                method="GET",
                path="/health",
            )

        shared_owner_limiter = RequestLimiter(
            policy=RateLimitPolicy(
                standard=RouteBudget(
                    owner_requests=1,
                    ip_requests=2,
                    window_seconds=60,
                    owner_concurrency=2,
                    ip_concurrency=2,
                )
            )
        )
        lease = await shared_owner_limiter.acquire(
            owner_id="owner-a",
            ip_address="203.0.113.10",
            method="GET",
            path="/health",
        )
        await lease.release()
        with pytest.raises(RateLimitExceeded, match="rate limit"):
            await shared_owner_limiter.acquire(
                owner_id="owner-a",
                ip_address="203.0.113.11",
                method="GET",
                path="/health",
            )

    asyncio.run(scenario())


def test_request_limiter_bounds_and_expiry_sweeps_identity_state():
    async def scenario() -> None:
        now = [0.0]
        limiter = RequestLimiter(
            policy=RateLimitPolicy(
                standard=RouteBudget(
                    owner_requests=20,
                    ip_requests=20,
                    window_seconds=60,
                    owner_concurrency=2,
                    ip_concurrency=2,
                )
            ),
            clock=lambda: now[0],
            maximum_tracked_identities=4,
        )

        for address in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
            lease = await limiter.acquire(
                owner_id="owner-a",
                ip_address=address,
                method="GET",
                path="/health",
            )
            await lease.release()
        assert limiter.tracked_identity_count == 4

        with pytest.raises(
            RateLimitExceeded, match="identity tracking limit"
        ):
            await limiter.acquire(
                owner_id="owner-a",
                ip_address="203.0.113.4",
                method="GET",
                path="/health",
            )

        now[0] = 61.0
        lease = await limiter.acquire(
            owner_id="owner-a",
            ip_address="203.0.113.4",
            method="GET",
            path="/health",
        )
        await lease.release()
        assert limiter.tracked_identity_count == 2

    asyncio.run(scenario())


def test_expensive_route_concurrency_collision_returns_429():
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowProductizer:
            async def preview_skus(self, *_: Any) -> list[Any]:
                started.set()
                await release.wait()
                return []

        limiter = RequestLimiter(
            policy=RateLimitPolicy(
                standard=_budget(requests=20, concurrency=8),
                gemini=_budget(requests=20, concurrency=1),
                payment=_budget(requests=20, concurrency=1),
                fulfillment=_budget(requests=20, concurrency=1),
            )
        )
        app = create_app(
            adapters=AdapterBundle(productizer=SlowProductizer()),
            rate_limiter=limiter,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            seller = await client.post(
                "/sellers",
                json={
                    "name": "Slow seller",
                    "agentUrl": "https://seller.example/agent",
                },
            )
            assert seller.status_code == 201, seller.text
            seller_id = seller.json()["sellerId"]
            capability = await client.post(
                f"/sellers/{seller_id}/capabilities",
                json={
                    "name": "Slow preview",
                    "description": "Wait for the concurrency assertion",
                },
            )
            assert capability.status_code == 201, capability.text

            preview_path = f"/sellers/{seller_id}/skus/preview"
            first_task = asyncio.create_task(client.post(preview_path, json={}))
            await asyncio.wait_for(started.wait(), timeout=2)
            collision = await client.post(preview_path, json={})
            assert collision.status_code == 429
            assert collision.json() == {
                "detail": "request concurrency limit exceeded"
            }
            assert collision.headers["retry-after"] == "1"
            release.set()
            first = await asyncio.wait_for(first_task, timeout=2)
            assert first.status_code == 200, first.text

    asyncio.run(scenario())


def test_non_offline_docs_hosts_headers_and_network_urls_are_fail_closed(
    tmp_path: Path,
):
    class LivePayment:
        mode = "testnet"
        independent_verification = True

    repository = SQLiteRepository(str(tmp_path / "commerce.sqlite3"))
    adapters = AdapterBundle(payment=LivePayment())
    try:
        with pytest.raises(RuntimeError, match="TRUSTED_HOSTS"):
            create_app(
                repository=repository,
                adapters=adapters,
                bearer_token="owner-token",
                payment_mode="testnet",
                trusted_hosts=[],
            )

        app = create_app(
            repository=repository,
            adapters=adapters,
            bearer_token="owner-token",
            payment_mode="testnet",
            trusted_hosts=["api.autonomerce.example.com"],
        )
        authorization = {"Authorization": "Bearer owner-token"}
        with TestClient(
            app,
            base_url="https://api.autonomerce.example.com",
        ) as client:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.headers["x-content-type-options"] == "nosniff"
            assert health.headers["x-frame-options"] == "DENY"
            assert health.headers["referrer-policy"] == "no-referrer"
            assert "max-age=63072000" in health.headers[
                "strict-transport-security"
            ]

            assert client.get("/openapi.json").status_code == 401
            assert (
                client.get("/openapi.json", headers=authorization).status_code
                == 404
            )
            assert client.get("/docs", headers=authorization).status_code == 404

            wrong_host = client.get(
                "/health",
                headers={"Host": "attacker.example"},
            )
            assert wrong_host.status_code == 400
            assert wrong_host.headers["x-frame-options"] == "DENY"

            fixture_url = client.post(
                "/sellers",
                headers=authorization,
                json={
                    "name": "Fixture-only seller",
                    "agentUrl": "https://seller.example/agent",
                },
            )
            assert fixture_url.status_code == 422
            assert fixture_url.json()["detail"] == (
                "seller agent URL must be a public HTTPS URL"
            )

            public_url = client.post(
                "/sellers",
                headers=authorization,
                json={
                    "name": "Public seller",
                    "agentUrl": "https://seller.autonomerce.com/agent",
                },
            )
            assert public_url.status_code == 201, public_url.text
    finally:
        repository.close()


def test_non_offline_startup_rejects_unverified_payment_adapter(tmp_path: Path):
    class UnverifiedLivePayment:
        mode = "testnet"

    repository = SQLiteRepository(str(tmp_path / "commerce.sqlite3"))
    try:
        with pytest.raises(
            RuntimeError,
            match="independent transaction verification",
        ):
            create_app(
                repository=repository,
                adapters=AdapterBundle(payment=UnverifiedLivePayment()),
                bearer_token="owner-token",
                payment_mode="testnet",
                trusted_hosts=["api.autonomerce.example.com"],
            )
    finally:
        repository.close()
