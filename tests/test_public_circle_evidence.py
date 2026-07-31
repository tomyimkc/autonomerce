from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "evidence" / "public"
TEMPLATES = ROOT / "evidence" / "templates"
TX_HASH = (
    "0xb3a036d46b71e93d37b69ddf1046ff1d708d1c4b33db73b863a4fa3d4a2f7d56"
)
PAYER = "0xd5eaf79637decd656e3adb52985cf0afb6cc29d8"
PAYEE = "0xebbcd5a37a086cbe0e978c26feff14e69bffa2a6"
ARC_USDC = "0x3600000000000000000000000000000000000000"


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _assert_transaction_schema_surface(record: dict) -> None:
    schema = _load(TEMPLATES / "transaction.public.schema.json")
    allowed = set(schema["properties"])
    required = set(schema["required"])

    assert required <= set(record)
    assert set(record) <= allowed
    assert record["schemaVersion"] == "autonomerce.transaction.public.v1"
    assert record["recordKind"] == "transaction"
    assert record["evidenceClassification"] in schema["properties"][
        "evidenceClassification"
    ]["enum"]
    assert re.fullmatch(
        schema["properties"]["proposalId"]["pattern"],
        record["proposalId"],
    )
    assert re.fullmatch(
        schema["properties"]["paymentId"]["pattern"],
        record["paymentId"],
    )
    assert re.fullmatch(
        schema["properties"]["amountUsdc"]["pattern"],
        record["amountUsdc"],
    )
    assert re.fullmatch(
        schema["properties"]["transactionHash"]["pattern"],
        record["transactionHash"],
    )
    datetime.fromisoformat(record["confirmedAt"].replace("Z", "+00:00"))
    datetime.fromisoformat(record["evidenceGeneratedAt"].replace("Z", "+00:00"))


def test_public_arc_transaction_is_schema_bounded_and_never_revenue():
    record = _load(PUBLIC / "circle-arc-testnet-transaction.public.json")
    _assert_transaction_schema_surface(record)

    assert record["synthetic"] is False
    assert record["evidenceClassification"] == "testnet"
    assert record["network"] == "ARC-TESTNET"
    assert record["token"] == "USDC"
    assert record["amountUsdc"] == "0.1"
    assert record["movesFunds"] is True
    assert record["transactionHash"] == TX_HASH
    assert record["explorerUrl"].endswith(TX_HASH)
    assert record["payerWallet"] == PAYER
    assert record["payeeWallet"] == PAYEE
    assert record["externalCustomer"] is False
    assert record["customerRelationship"] == "founder"
    assert record["countedAsRevenue"] is False
    assert record["delivered"] is False
    assert record["acceptanceVerdict"] == "pending"
    assert record["customerConsentToPublish"] is False
    assert all("idempotency" not in key.lower() for key in record)


def test_public_wallet_policy_matches_the_bounded_testnet_receipt():
    policy = _load(PUBLIC / "wallet-policy.redacted.json")
    transaction = _load(
        PUBLIC / "circle-arc-testnet-transaction.public.json"
    )

    assert policy["provider"] == "circle"
    assert policy["walletSurface"] == "Circle Agent Wallet"
    assert policy["environment"] == "testnet"
    assert policy["network"] == transaction["network"]
    assert policy["token"] == transaction["token"]
    assert policy["canonicalAsset"] == ARC_USDC
    assert policy["payerWallet"] == transaction["payerWallet"]
    assert policy["payeeWallet"] == transaction["payeeWallet"]

    bounds = policy["applicationPolicy"]
    assert bounds["maximumPerPaymentUsdc"] == transaction["amountUsdc"]
    assert bounds["maximumTotalUsdc"] == "0.2"
    assert bounds["maximumPaymentCount"] == 2
    assert bounds["payerAllowlistRequired"] is True
    assert bounds["payeeAllowlistRequired"] is True
    assert bounds["selfPaymentAllowed"] is False
    assert bounds["mainnetEnabled"] is False
    assert bounds["durableStore"] == "SQLite"

    attempts = policy["observedAttempts"]
    assert [attempt["result"] for attempt in attempts] == [
        "not_submitted",
        "not_submitted",
        "confirmed",
    ]
    assert [attempt["fundsMoved"] for attempt in attempts] == [
        False,
        False,
        True,
    ]
    assert attempts[-1]["transactionHash"] == TX_HASH
    assert attempts[-1]["idempotentReplayVerified"] is True


def test_existing_synthetic_transaction_remains_distinct_from_testnet_proof():
    synthetic = _load(PUBLIC / "transactions.public.json")
    testnet = _load(PUBLIC / "circle-arc-testnet-transaction.public.json")
    _assert_transaction_schema_surface(synthetic)

    assert synthetic["synthetic"] is True
    assert synthetic["evidenceClassification"] == "synthetic"
    assert synthetic["movesFunds"] is False
    assert synthetic["countedAsRevenue"] is False
    assert synthetic["paymentId"] != testnet["paymentId"]
    assert synthetic["transactionHash"] != testnet["transactionHash"]
