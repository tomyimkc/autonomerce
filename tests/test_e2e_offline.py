from __future__ import annotations

import json
from importlib.resources import files
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages"))

from autonomerce.demo import LaneBindings, run_offline_demo  # noqa: E402


EXPECTED_STEPS = [
    "seller_capability",
    "sku",
    "opted_in_buyer_need",
    "proposal",
    "bounded_acceptance",
    "mock_payment",
    "fulfillment",
    "public_delivery_revenue_receipt",
]
STABLE_ID = re.compile(
    r"^(?:cap|sku|need|proposal|payment|fulfillment|order|receipt)_[a-f0-9]{24}$"
)


def _deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline demo attempted network access")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def _real_bindings_or_skip() -> LaneBindings:
    bindings = LaneBindings.discover()
    if bindings.missing_lanes:
        pytest.skip(
            "parallel Autonomerce lanes are still landing: "
            + ", ".join(bindings.missing_lanes)
        )
    return bindings


def test_real_lanes_complete_one_deterministic_offline_sale(monkeypatch):
    _deny_network(monkeypatch)
    bindings = _real_bindings_or_skip()

    first = run_offline_demo(bindings=bindings).to_dict()
    second = run_offline_demo(bindings=bindings).to_dict()
    assert first == second

    assert [step["step"] for step in first["trace"]] == EXPECTED_STEPS
    assert first["diagnostics"] == {
        "allLanesAvailable": True,
        "artifactPublished": False,
        "availableLanes": ["agents", "payments", "sales", "offerrail"],
        "commercialPolicyAllowed": True,
        "credentialsUsed": False,
        "idempotentPaymentReplay": True,
        "ledgerEntries": 4,
        "ledgerVerified": True,
        "networkCalls": 0,
        "offline": True,
        "paymentExecutorCalls": 1,
        "realFundsMoved": False,
        "sellerFulfillmentCalls": 1,
    }

    public = first["publicReceipt"]
    assert public["status"] == "delivered"
    assert public["acceptanceVerdict"] == "accepted"
    assert public["revenue"]["settlementKind"] == "simulated"
    assert public["revenue"]["movesFunds"] is False
    assert public["revenue"]["amountUsdc"] == first["trace"][4]["amountUsdc"]
    assert public["delivery"]["accepted"] is True
    assert public["ledger"]["chainVerified"] is True

    ids = [
        first["trace"][0]["capabilityId"],
        first["trace"][1]["skuId"],
        first["trace"][2]["needId"],
        first["trace"][3]["proposalId"],
        first["trace"][5]["paymentId"],
        first["trace"][6]["fulfillmentId"],
        public["orderId"],
        public["ledger"]["receiptId"],
    ]
    assert all(STABLE_ID.fullmatch(value) for value in ids)


def test_e2e_uses_real_lane_implementations_when_present():
    bindings = _real_bindings_or_skip()
    implementations = run_offline_demo(bindings=bindings).implementations

    assert implementations["productizer"].startswith("autonomerce.agents.")
    assert implementations["fitScorer"].startswith("autonomerce.agents.")
    assert implementations["deliveryValidator"].startswith("autonomerce.agents.")
    assert implementations["prospectRegistry"].startswith("autonomerce.sales.")
    assert implementations["pitchWorkflow"].startswith("autonomerce.sales.")
    assert implementations["negotiation"].startswith("autonomerce.sales.")
    assert implementations["fulfillment"].startswith("autonomerce.sales.")
    assert implementations["paymentProcessor"].startswith("autonomerce.payments.")
    assert implementations["paymentExecutor"].startswith("autonomerce.payments.")
    assert implementations["catalog"].startswith("offerrail.")
    assert implementations["receiptLedger"].startswith("offerrail.")


def test_public_receipt_excludes_private_input_credentials_and_artifact():
    result = run_offline_demo(bindings=_real_bindings_or_skip()).to_dict()
    public_text = json.dumps(result["publicReceipt"], sort_keys=True).lower()
    fixture_need = json.loads(
        (ROOT / "examples" / "fixtures" / "buyer-need.json").read_text()
    )
    artifact = json.loads(
        (ROOT / "examples" / "fixtures" / "fulfillment-artifact.json").read_text()
    )

    assert "buyer.example" not in public_text
    assert fixture_need["inputPayload"]["goal"].lower() not in public_text
    assert artifact["brief"].lower() not in public_text
    assert "idempotency" not in public_text
    for forbidden in (
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "session_token",
        "private_key",
        "password",
        "secret",
        "credential",
    ):
        assert forbidden not in public_text


def test_repo_local_cli_is_the_one_command_demo():
    _real_bindings_or_skip()
    environment = os.environ.copy()
    for key in tuple(environment):
        if any(
            marker in key.upper()
            for marker in (
                "GOOGLE_API",
                "GOOGLE_APPLICATION_CREDENTIALS",
                "CIRCLE",
                "PRIVATE_KEY",
                "MNEMONIC",
                "ACCESS_TOKEN",
            )
        ):
            environment.pop(key)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples" / "run_offline_demo.py"),
            "--compact",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["publicReceipt"]["status"] == "delivered"
    assert payload["diagnostics"]["networkCalls"] == 0
    assert payload["diagnostics"]["credentialsUsed"] is False
    assert payload["diagnostics"]["realFundsMoved"] is False


def test_packaged_demo_fixtures_match_reviewer_visible_examples():
    packaged = files("autonomerce.demo").joinpath("fixtures")
    examples = ROOT / "examples" / "fixtures"

    fixture_names = (
        "buyer-agent-card.json",
        "buyer-need.json",
        "fulfillment-artifact.json",
        "seller-agent-card.json",
    )
    for fixture_name in fixture_names:
        assert packaged.joinpath(fixture_name).read_bytes() == (
            examples / fixture_name
        ).read_bytes()
