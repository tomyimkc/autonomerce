from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.api.adapters import (  # noqa: E402
    AdapterConfigurationError,
    GeminiProductizerAdapter,
    MockPaymentAdapter,
    OfflineFulfillmentAdapter,
    OfflineProductizer,
    SellerAgentFulfillmentAdapter,
    load_optional_adapters,
)
from autonomerce.contracts import (  # noqa: E402
    CapabilityDescriptor,
    ContractError,
    Proposal,
    ProposalState,
)


class FakeGeminiModels:
    def __init__(self) -> None:
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed={
                "skus": [
                    {
                        "name": "Gemini evidence verifier",
                        "outcome": "Return a Gemini-composed evidence verdict.",
                        "basePriceUsdc": "1.5",
                        "acceptanceCriteria": ["provider_summary_present"],
                        "maximumLatencySeconds": 90,
                        "capacityPerHour": 4,
                    }
                ],
                "summary": "Productized through the configured Gemini provider.",
                "reasonCodes": ["GEMINI_PRODUCTIZED"],
            }
        )


class FakeLivePaymentAdapter:
    mode = "testnet"
    independent_verification = True

    def execute_payment(self, *args, **kwargs):  # pragma: no cover - composition only
        raise AssertionError("payment execution is outside composition tests")


class FakeSellerExecutor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, proposal, *, context):
        self.calls.append((proposal, dict(context)))
        return {
            "verdict": "seller-produced",
            "proposalId": proposal.proposal_id,
        }


def capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id="cap_verify",
        name="Source verification",
        description="Return a cited support, refute, or abstain verdict.",
        input_schema={"type": "object", "required": ["claim"]},
        output_schema={
            "type": "object",
            "required": ["verdict"],
            "properties": {"verdict": {"type": "string"}},
        },
        tags=("verification",),
    )


def proposal() -> Proposal:
    return Proposal(
        proposal_id="proposal_adapter_composition",
        seller_agent_url="https://seller.example/a2a",
        buyer_agent_url="https://buyer.example/a2a",
        sku_id="sku_verify",
        problem_observed="A claim needs verification.",
        offered_outcome="Return a verdict.",
        price_usdc=Decimal("1"),
        delivery_seconds=120,
        acceptance_criteria=("non_empty_artifact", "required_field:verdict"),
        state=ProposalState.PAID,
    )


def test_offline_mode_is_deterministic_and_imports_no_optional_lanes():
    def forbidden_import(name):
        raise AssertionError(f"offline mode imported {name}")

    first = load_optional_adapters(
        environment={
            "AUTONOMERCE_MODE": "offline",
            "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
        },
        module_loader=forbidden_import,
    )
    second = load_optional_adapters(
        environment={
            "AUTONOMERCE_MODE": "offline",
            "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
        },
        module_loader=forbidden_import,
    )

    assert isinstance(first.productizer, OfflineProductizer)
    assert isinstance(first.payment, MockPaymentAdapter)
    assert isinstance(first.fulfillment, OfflineFulfillmentAdapter)
    assert first.diagnostics == second.diagnostics
    assert first.diagnostics["runtimeMode"] == "offline"
    assert first.diagnostics["movesFunds"] is False

    seller = {"seller_id": "seller_1", "network": "ARC-TESTNET"}
    options = {
        "base_price_usdc": Decimal("1"),
        "maximum_latency_seconds": 120,
        "capacity_per_hour": 2,
        "variants": 2,
    }
    assert first.productizer.preview_skus(
        seller, [capability()], options
    ) == second.productizer.preview_skus(seller, [capability()], options)

    payment_args = {
        "idempotency_key": "offline-idempotency",
        "chain": "ARC-TESTNET",
        "token": "USDC",
        "payer_wallet": "0x1111111111111111111111111111111111111111",
        "payee_wallet": "0x2222222222222222222222222222222222222222",
        "public": False,
    }
    assert first.payment.execute_payment(
        proposal(), **payment_args
    ) == second.payment.execute_payment(proposal(), **payment_args)
    assert first.fulfillment.fulfill(
        proposal(),
        artifact={"verdict": "offline"},
        context={},
    ) == second.fulfillment.fulfill(
        proposal(),
        artifact={"verdict": "offline"},
        context={},
    )


def test_gemini_mode_uses_gemini_provider_and_capability_productizer():
    models = FakeGeminiModels()
    client = SimpleNamespace(models=models)
    bundle = load_optional_adapters(
        environment={
            "AUTONOMERCE_MODE": "gemini",
            "AUTONOMERCE_GEMINI_MODEL": "gemini-test-model",
        },
        gemini_client=client,
    )

    assert isinstance(bundle.productizer, GeminiProductizerAdapter)
    assert isinstance(bundle.payment, MockPaymentAdapter)
    assert isinstance(bundle.fulfillment, OfflineFulfillmentAdapter)
    skus = bundle.productizer.preview_skus(
        {"seller_id": "seller_gemini", "network": "ARC-TESTNET"},
        [capability()],
        {
            "base_price_usdc": Decimal("1"),
            "maximum_latency_seconds": 120,
            "capacity_per_hour": 5,
            "acceptance_criteria": ["owner_check"],
            "variants": 2,
        },
    )

    assert len(models.calls) == 1
    assert models.calls[0]["model"] == "gemini-test-model"
    assert models.calls[0]["config"]["response_mime_type"] == "application/json"
    assert skus[0].name == "Gemini evidence verifier"
    assert skus[0].outcome == "Return a Gemini-composed evidence verdict."
    assert skus[0].base_price_usdc == Decimal("1.5")
    assert skus[0].input_schema == capability().input_schema
    assert skus[0].output_schema == capability().output_schema
    assert "owner_check" in skus[0].acceptance_criteria
    assert "output_schema_valid" in skus[0].acceptance_criteria
    assert bundle.diagnostics["productizer"] == "google:gemini-test-model"


def test_requested_live_payment_never_falls_back_to_mock():
    def broken_payment_factory(*, environment):
        assert environment["AUTONOMERCE_PAYMENT_MODE"] == "testnet"
        assert (
            environment["AUTONOMERCE_PAYMENT_MAX_PER_PAYMENT_USDC"] == "1"
        )
        assert environment["AUTONOMERCE_PAYMENT_MAX_TOTAL_USDC"] == "10"
        raise RuntimeError("injected live configuration failure")

    with pytest.raises(
        AdapterConfigurationError,
        match="live payment adapter failed to load",
    ):
        load_optional_adapters(
            environment={
                "AUTONOMERCE_MODE": "live",
                "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
                "AUTONOMERCE_CIRCLE_MAX_PER_TX_USDC": "1",
                "AUTONOMERCE_CIRCLE_MAX_DAILY_USDC": "10",
            },
            gemini_client=SimpleNamespace(models=FakeGeminiModels()),
            payment_factory=broken_payment_factory,
            seller_agent_executor=FakeSellerExecutor(),
        )

    with pytest.raises(
        AdapterConfigurationError,
        match="live payment mode was requested",
    ):
        load_optional_adapters(
            environment={
                "AUTONOMERCE_MODE": "offline",
                "AUTONOMERCE_PAYMENT_MODE": "testnet",
            }
        )


def test_live_mode_requires_explicit_seller_agent_executor():
    with pytest.raises(
        AdapterConfigurationError,
        match="live fulfillment requires",
    ):
        load_optional_adapters(
            environment={
                "AUTONOMERCE_MODE": "live",
                "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
            },
            gemini_client=SimpleNamespace(models=FakeGeminiModels()),
            payment_adapter=FakeLivePaymentAdapter(),
        )


def test_live_fulfillment_rejects_caller_artifact_and_uses_seller_output():
    executor = FakeSellerExecutor()
    bundle = load_optional_adapters(
        environment={
            "AUTONOMERCE_MODE": "live",
            "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
        },
        gemini_client=SimpleNamespace(models=FakeGeminiModels()),
        payment_adapter=FakeLivePaymentAdapter(),
        seller_agent_executor=executor,
    )

    assert isinstance(bundle.fulfillment, SellerAgentFulfillmentAdapter)
    with pytest.raises(ContractError, match="caller-authored"):
        bundle.fulfillment.fulfill(
            proposal(),
            artifact={"verdict": "caller-forged"},
            context={
                "payment_id": "payment_1",
                "acceptance_results": {"forged": True},
            },
        )
    assert executor.calls == []

    result = bundle.fulfillment.fulfill(
        proposal(),
        artifact=None,
        context={
            "payment_id": "payment_1",
            "acceptance_results": {"forged": True},
        },
    )
    assert result["verdict"] == "seller-produced"
    assert len(executor.calls) == 1
    assert executor.calls[0][1] == {"payment_id": "payment_1"}


def test_bundle_exposes_secret_free_health_compatible_adapter_modes():
    executor = FakeSellerExecutor()
    bundle = load_optional_adapters(
        environment={
            "AUTONOMERCE_MODE": "live",
            "AUTONOMERCE_CIRCLE_NETWORK": "ARC-TESTNET",
            "AUTONOMERCE_GEMINI_MODEL": "gemini-health-model",
            "GOOGLE_API_KEY": "must-not-appear",
        },
        gemini_client=SimpleNamespace(models=FakeGeminiModels()),
        payment_adapter=FakeLivePaymentAdapter(),
        seller_agent_executor=executor,
    )

    integrations = dict(bundle.sources)
    assert integrations["runtimeMode"] == "live"
    assert integrations["paymentMode"] == "testnet"
    assert integrations["movesFunds"] is True
    assert integrations["productizer"] == "google:gemini-health-model"
    assert "FakeSellerExecutor" in integrations["fulfillment"]
    assert "must-not-appear" not in json.dumps(integrations)
