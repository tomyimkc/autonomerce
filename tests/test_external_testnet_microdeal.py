from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_external_testnet_microdeal as script  # noqa: E402
from autonomerce.payments import (  # noqa: E402
    ARC_TESTNET_USDC,
    ExecutionResult,
    PaymentMode,
    SQLitePaymentStore,
)


PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
TX_HASH = "0x" + ("a" * 64)
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class StaticGeminiProvider:
    provider_name = "google"
    model_name = "gemini-test-fixture"

    def __init__(self) -> None:
        self.requests = []

    def generate_json(self, request):
        self.requests.append(request)
        return {
            "skus": [
                {
                    "name": "Gemini-advised evidence verification",
                    "relevant": True,
                    "rationale": "Matches the bounded verification capability.",
                }
            ],
            "summary": "Prepared bounded advisory copy.",
            "reasonCodes": ["COPY_RELEVANT"],
        }


class FakeCircleExecutor:
    mode = PaymentMode.TESTNET

    def __init__(self) -> None:
        self.build_calls = []
        self.execute_calls = []

    def build_argv(self, intent):
        self.build_calls.append(intent)
        assert intent.chain == "ARC-TESTNET"
        assert intent.asset == ARC_TESTNET_USDC
        assert intent.amount_usdc == Decimal("0.10")
        return ["circle", "wallet", "transfer"]

    def execute(self, intent):
        self.execute_calls.append(intent)
        return ExecutionResult(
            state="CONFIRMED",
            amount_usdc=intent.amount_usdc,
            chain=intent.chain,
            payer_wallet=intent.payer_wallet,
            payee_wallet=intent.payee_wallet,
            transaction_hash=TX_HASH,
            confirmed_at="2026-08-01T12:00:00Z",
            explorer_url=None,
            simulated=False,
            provider_reference="fake-circle-testnet",
            token=intent.token,
            asset=intent.asset,
        )


def _customer_record() -> dict:
    return {
        "schemaVersion": "autonomerce.external_customer.private.v1",
        "customerRecordId": "customer-private-001",
        "customerName": "Ada Design Partner",
        "email": "ada.private@example.invalid",
        "credentialNotes": "Bearer customer-private-credential",  # secret-scan: allow-test-fixture
        "relationship": {
            "relationshipRecordId": "relationship-private-001",
            "classification": "external_design_partner",
            "notes": "Prior design-partner conversation.",
        },
        "consent": {
            "consentRecordId": "consent-private-001",
            "status": "granted",
            "designPartnerPilot": True,
            "testnetMicrodeal": True,
            "publishRedactedEvidence": True,
        },
        "buyerAgentUrl": "https://buyer.partner.example/a2a",
        "claims": [
            {
                "claim": "Ada's private API supports structured output.",
                "sources": [
                    {
                        "sourceId": "source-private-1",
                        "url": "https://evidence.example/report-one?case=ada-private",
                        "title": "Private report one",
                        "excerpt": "The supplied report states structured output is supported.",
                        "stance": "support",
                    }
                ],
            },
            {
                "claim": "The private deployment emits evidence receipts.",
                "sources": [
                    {
                        "sourceId": "source-private-2",
                        "url": "https://evidence.example/report-two",
                        "title": "Private report two",
                        "excerpt": "The supplied report shows an evidence receipt.",
                        "stance": "support",
                    }
                ],
            },
        ],
    }


def _write_customer_record(tmp_path: Path, value: dict | None = None) -> Path:
    path = tmp_path / "customer.private.json"
    path.write_text(
        json.dumps(value or _customer_record()),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _config(tmp_path: Path, customer_path: Path) -> script.RunConfiguration:
    return script.RunConfiguration(
        microdeal_id="microdeal-external-001",
        customer_record_path=customer_path,
        payer_wallet=PAYER,
        payee_wallet=PAYEE,
        circle_cli_binary=tmp_path / "circle",
        circle_cli_sha256="1" * 64,
        sqlite_path=tmp_path / "payments.sqlite3",
        private_evidence_path=tmp_path / "microdeal.private.json",
        public_evidence_path=tmp_path / "microdeal.public.json",
    )


def _executor_factory(fake: FakeCircleExecutor, constructor_calls: list[dict]):
    def factory(**kwargs):
        constructor_calls.append(kwargs)
        return fake

    return factory


def _lookup_factory(calls: list[str]):
    def factory():
        def lookup(transaction_hash: str):
            calls.append(transaction_hash)
            return {
                "confirmed": True,
                "chain": "ARC-TESTNET",
                "amountUsdc": "0.1",
                "payerWallet": PAYER,
                "payeeWallet": PAYEE,
                "transactionHash": transaction_hash,
                "token": "USDC",
                "asset": ARC_TESTNET_USDC,
            }

        return lookup

    return factory


def test_dry_run_is_default_and_never_executes_or_writes_evidence(tmp_path):
    customer_path = _write_customer_record(tmp_path)
    config = _config(tmp_path, customer_path)
    provider = StaticGeminiProvider()
    executor = FakeCircleExecutor()
    constructor_calls: list[dict] = []
    lookup_calls: list[str] = []

    result = script.run_microdeal(
        config,
        provider=provider,
        executor_factory=_executor_factory(executor, constructor_calls),
        lookup_factory=_lookup_factory(lookup_calls),
    )

    assert result["mode"] == "dry-run"
    assert result["transferExecuted"] is False
    assert result["policyWouldAuthorize"] is True
    assert result["proposalState"] == "accepted"
    assert result["amountUsdc"] == "0.1"
    assert result["maximumPerPaymentUsdc"] == "0.1"
    assert result["maximumTotalUsdc"] == "0.1"
    assert result["maximumPaymentCount"] == 1
    assert result["claimCount"] == 2
    assert result["externalCustomer"] is True
    assert result["fundingSource"] == "founder_sponsored_testnet"
    assert result["countedAsRevenue"] is False
    assert result["payingCustomer"] is False
    assert result["delivered"] is False
    assert result["acceptanceVerdict"] == "pending"
    assert result["evidenceWritten"] is False
    assert len(provider.requests) == 1
    provider_request = json.dumps(provider.requests[0].payload)
    assert "Ada Design Partner" not in provider_request
    assert "ada.private@example.invalid" not in provider_request
    assert "customer-private-001" not in provider_request
    assert "Ada's private API" not in provider_request
    assert len(executor.build_calls) == 1
    assert executor.execute_calls == []
    assert lookup_calls == []
    assert constructor_calls == [
        {
            "mode": PaymentMode.TESTNET,
            "binary": str(config.circle_cli_binary),
            "binary_sha256": config.circle_cli_sha256,
            "working_directory": "/",
        }
    ]
    assert not config.private_evidence_path.exists()
    assert not config.public_evidence_path.exists()
    assert SQLitePaymentStore(config.sqlite_path).list() == ()


def test_inexact_execution_phrase_fails_before_provider_executor_or_lookup(
    tmp_path,
):
    customer_path = _write_customer_record(tmp_path)
    config = _config(tmp_path, customer_path)
    provider = StaticGeminiProvider()
    called = {"executor": False, "lookup": False}

    def forbidden_executor(**kwargs):
        called["executor"] = True
        raise AssertionError("executor must not be constructed")

    def forbidden_lookup():
        called["lookup"] = True
        raise AssertionError("lookup must not be constructed")

    with pytest.raises(ValueError, match="exact external Arc testnet"):
        script.run_microdeal(
            config,
            dry_run=False,
            confirmation="EXECUTE_EXTERNAL_MICRODEAL",
            provider=provider,
            executor_factory=forbidden_executor,
            lookup_factory=forbidden_lookup,
        )

    assert provider.requests == []
    assert called == {"executor": False, "lookup": False}
    assert not config.sqlite_path.exists()
    assert not config.private_evidence_path.exists()
    assert not config.public_evidence_path.exists()


def test_execute_links_customer_gemini_payment_fulfillment_and_redacted_evidence(
    tmp_path,
):
    customer = _customer_record()
    customer_path = _write_customer_record(tmp_path, customer)
    config = _config(tmp_path, customer_path)
    provider = StaticGeminiProvider()
    executor = FakeCircleExecutor()
    constructor_calls: list[dict] = []
    lookup_calls: list[str] = []
    factory = _executor_factory(executor, constructor_calls)
    lookup_factory = _lookup_factory(lookup_calls)

    result = script.run_microdeal(
        config,
        dry_run=False,
        confirmation=script.TESTNET_EXECUTION_CONFIRMATION,
        provider=provider,
        executor_factory=factory,
        lookup_factory=lookup_factory,
        now=NOW,
    )

    assert result["mode"] == "external-testnet-microdeal"
    assert result["transferExecuted"] is True
    assert result["movesFunds"] is True
    assert result["transactionHash"] == TX_HASH
    assert result["idempotentReplayVerified"] is True
    assert result["independentLookupVerified"] is True
    assert result["externalCustomer"] is True
    assert result["fundingSource"] == "founder_sponsored_testnet"
    assert result["countedAsRevenue"] is False
    assert result["payingCustomer"] is False
    assert result["delivered"] is True
    assert result["acceptanceVerdict"] == "accepted"
    assert len(executor.execute_calls) == 1
    assert lookup_calls == [TX_HASH]
    assert len(constructor_calls) == 1
    assert len(SQLitePaymentStore(config.sqlite_path).list()) == 1

    private = json.loads(
        config.private_evidence_path.read_text(encoding="utf-8")
    )
    public = json.loads(
        config.public_evidence_path.read_text(encoding="utf-8")
    )

    assert private["customerRecord"] == customer
    assert private["customerRelationshipRecordId"] == (
        "relationship-private-001"
    )
    assert private["consentRecordId"] == "consent-private-001"
    assert private["acceptedProposal"]["price_usdc"] == "0.1"
    assert private["payment"]["idempotencyKey"].startswith("idem_")
    assert private["payment"]["payerWallet"] == PAYER
    assert private["payment"]["payeeWallet"] == PAYEE
    assert private["fulfillment"]["accepted"] is True
    assert private["fulfillment"]["artifact"]["claimCount"] == 2
    assert private["fulfillment"]["finalProposalState"] == "delivered"

    assert public["schemaVersion"] == (
        "autonomerce.external_testnet_microdeal.public.v1"
    )
    assert public["evidenceClassification"] == "testnet"
    assert public["network"] == "ARC-TESTNET"
    assert public["token"] == "USDC"
    assert public["asset"] == ARC_TESTNET_USDC
    assert public["amountUsdc"] == "0.1"
    assert public["movesFunds"] is True
    assert public["transactionHash"] == TX_HASH
    assert public["externalCustomer"] is True
    assert public["customerRelationship"] == "external_design_partner"
    assert public["customerConsentToPublish"] is True
    assert public["buyerAgentUrl"] == customer["buyerAgentUrl"]
    assert public["fundingSource"] == "founder_sponsored_testnet"
    assert public["countedAsRevenue"] is False
    assert public["payingCustomer"] is False
    assert public["claimCount"] == 2
    assert public["sourceUrlCount"] == 2
    assert len(public["sourceUrlHashes"]) == 2
    assert public["delivered"] is True
    assert public["acceptanceVerdict"] == "accepted"
    assert public["independentLookupVerified"] is True
    assert public["idempotentReplayVerified"] is True
    assert public["productizerProvider"] == "google"
    assert public["productizerModel"] == "gemini-test-fixture"
    assert public["payerWallet"] is None
    assert public["payeeWallet"] is None
    assert public["customerRecordId"] != "customer-private-001"
    assert (
        public["customerRelationshipRecordId"]
        != "relationship-private-001"
    )
    assert public["consentRecordId"] != "consent-private-001"

    public_text = json.dumps(public)
    for forbidden in (
        "Ada Design Partner",
        "ada.private@example.invalid",
        "customer-private-credential",
        "customer-private-001",
        "relationship-private-001",
        "consent-private-001",
        "Ada's private API",
        "Private report one",
        "case=ada-private",
        PAYER,
        PAYEE,
    ):
        assert forbidden.lower() not in public_text.lower()
    assert private["payment"]["idempotencyKey"] not in public_text

    assert stat.S_IMODE(config.private_evidence_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.public_evidence_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.sqlite_path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".*.tmp"))

    replay = script.run_microdeal(
        config,
        dry_run=False,
        confirmation=script.TESTNET_EXECUTION_CONFIRMATION,
        provider=provider,
        executor_factory=factory,
        lookup_factory=lookup_factory,
        now=NOW,
    )

    assert replay["transferExecuted"] is False
    assert replay["transactionHash"] == result["transactionHash"]
    assert replay["paymentId"] == result["paymentId"]
    assert replay["proposalId"] == result["proposalId"]
    assert replay["idempotentReplayVerified"] is True
    assert len(executor.execute_calls) == 1
    assert lookup_calls == [TX_HASH, TX_HASH]
    assert len(SQLitePaymentStore(config.sqlite_path).list()) == 1


def test_delivery_and_acceptance_fail_closed_when_artifact_validation_fails(
    tmp_path,
):
    customer_path = _write_customer_record(tmp_path)
    config = _config(tmp_path, customer_path)
    provider = StaticGeminiProvider()
    executor = FakeCircleExecutor()
    lookup_calls: list[str] = []

    class InvalidFulfillmentExecutor:
        def execute(self, proposal, *, context):
            assert context["buyerInput"]["claims"]
            return {"unexpected": "artifact"}

    def fulfillment_factory(**kwargs):
        assert list(kwargs["sku_contracts"].values()) == [
            script.FULFILLMENT_KIND
        ]
        return InvalidFulfillmentExecutor()

    result = script.run_microdeal(
        config,
        dry_run=False,
        confirmation=script.TESTNET_EXECUTION_CONFIRMATION,
        provider=provider,
        executor_factory=lambda **kwargs: executor,
        lookup_factory=_lookup_factory(lookup_calls),
        fulfillment_executor_factory=fulfillment_factory,
        now=NOW,
    )

    public = json.loads(
        config.public_evidence_path.read_text(encoding="utf-8")
    )
    private = json.loads(
        config.private_evidence_path.read_text(encoding="utf-8")
    )
    assert len(executor.execute_calls) == 1
    assert result["delivered"] is False
    assert result["acceptanceVerdict"] == "rejected"
    assert public["delivered"] is False
    assert public["acceptanceVerdict"] == "rejected"
    assert any(value is False for value in public["acceptanceResults"].values())
    assert private["fulfillment"]["accepted"] is False
    assert private["fulfillment"]["finalProposalState"] == "failed"
    assert "OUTPUT_SCHEMA_INVALID" in private["fulfillment"]["reasonCodes"]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda record: record.update(claims=[]),
            "1 to 5 claims",
        ),
        (
            lambda record: record.update(
                claims=[
                    {
                        "claim": f"claim-{index}",
                        "sources": [
                            {"url": "https://evidence.example/report"}
                        ],
                    }
                    for index in range(6)
                ]
            ),
            "1 to 5 claims",
        ),
        (
            lambda record: record["claims"][0]["sources"][0].update(
                url="http://evidence.example/report"
            ),
            "must be HTTPS",
        ),
        (
            lambda record: record["consent"].update(
                publishRedactedEvidence=False
            ),
            "redacted public evidence consent",
        ),
        (
            lambda record: record["relationship"].update(
                classification="founder_internal"
            ),
            "external_design_partner",
        ),
        (
            lambda record: record.update(
                buyerAgentUrl="https://user:password@buyer.example/a2a"
            ),
            "public HTTPS",
        ),
    ],
)
def test_customer_record_validation_fails_before_payment(
    tmp_path,
    mutate,
    message,
):
    customer = _customer_record()
    mutate(customer)
    customer_path = _write_customer_record(tmp_path, customer)
    config = _config(tmp_path, customer_path)
    provider = StaticGeminiProvider()
    executor = FakeCircleExecutor()

    with pytest.raises(ValueError, match=message):
        script.run_microdeal(
            config,
            provider=provider,
            executor_factory=lambda **kwargs: executor,
            lookup_factory=lambda: lambda transaction_hash: None,
        )

    assert provider.requests == []
    assert executor.build_calls == []
    assert executor.execute_calls == []
    assert not config.sqlite_path.exists()
    assert not config.private_evidence_path.exists()
    assert not config.public_evidence_path.exists()


@pytest.mark.parametrize(
    "unsafe",
    [
        {"customerEmail": "ada.private@example.invalid"},
        {"apiKey": "AIza012345678901234567890123456789"},  # secret-scan: allow-test-fixture
        {"notes": "Bearer customer-private-credential"},  # secret-scan: allow-test-fixture
        {"customerName": "Ada Design Partner"},
    ],
)
def test_public_evidence_guard_rejects_pii_and_credentials(unsafe):
    customer = _customer_record()
    with pytest.raises(ValueError, match="PII|credential"):
        script._assert_public_evidence_safe(
            {
                "schemaVersion": "test",
                **unsafe,
            },
            customer_record=customer,
            allowed_public_values=(customer["buyerAgentUrl"],),
        )


def test_cli_defaults_to_dry_run_and_has_no_authentication_step(
    tmp_path,
    capsys,
):
    customer_path = _write_customer_record(tmp_path)
    config = _config(tmp_path, customer_path)
    provider = StaticGeminiProvider()
    executor = FakeCircleExecutor()
    lookup_calls: list[str] = []

    assert (
        script.main(
            [
                "--microdeal-id",
                config.microdeal_id,
                "--customer-record",
                str(config.customer_record_path),
                "--payer-wallet",
                config.payer_wallet,
                "--payee-wallet",
                config.payee_wallet,
                "--circle-cli-binary",
                str(config.circle_cli_binary),
                "--circle-cli-sha256",
                config.circle_cli_sha256,
                "--sqlite-path",
                str(config.sqlite_path),
                "--private-evidence-path",
                str(config.private_evidence_path),
                "--public-evidence-path",
                str(config.public_evidence_path),
            ],
            provider=provider,
            executor_factory=lambda **kwargs: executor,
            lookup_factory=_lookup_factory(lookup_calls),
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["transferExecuted"] is False
    assert executor.execute_calls == []
    assert lookup_calls == []
    assert not config.private_evidence_path.exists()
    assert not config.public_evidence_path.exists()


def test_cli_rejects_inexact_phrase_before_creating_files(tmp_path):
    customer_path = _write_customer_record(tmp_path)
    config = _config(tmp_path, customer_path)

    with pytest.raises(SystemExit) as failure:
        script.main(
            [
                "--confirm-testnet-microdeal",
                "EXECUTE_ONE_TESTNET_MICRODEAL",
                "--microdeal-id",
                config.microdeal_id,
                "--customer-record",
                str(config.customer_record_path),
                "--payer-wallet",
                config.payer_wallet,
                "--payee-wallet",
                config.payee_wallet,
                "--circle-cli-binary",
                str(config.circle_cli_binary),
                "--circle-cli-sha256",
                config.circle_cli_sha256,
                "--sqlite-path",
                str(config.sqlite_path),
                "--private-evidence-path",
                str(config.private_evidence_path),
                "--public-evidence-path",
                str(config.public_evidence_path),
            ],
        )

    assert failure.value.code == 2
    assert not config.sqlite_path.exists()
    assert not config.private_evidence_path.exists()
    assert not config.public_evidence_path.exists()
