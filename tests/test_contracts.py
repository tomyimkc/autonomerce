from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.contracts import (  # noqa: E402
    CommercialPolicy,
    ContractError,
    PaymentReceipt,
    PaymentState,
    ServiceSKU,
    stable_id,
    usdc,
    usdc_text,
)


def test_stable_id_is_deterministic_and_prefixed():
    first = stable_id("sku", "agent", "verify")
    assert first == stable_id("sku", "agent", "verify")
    assert first.startswith("sku_")
    assert len(first) == 28


def test_usdc_is_exact_and_bounded_to_six_decimals():
    assert usdc_text(usdc("1.230000")) == "1.23"
    assert usdc("0.000001") == Decimal("0.000001")
    try:
        usdc("0.0000001")
    except ContractError:
        pass
    else:
        raise AssertionError("sub-micro-USDC value must fail")


def test_policy_rejects_inverted_price_bounds():
    try:
        CommercialPolicy(
            policy_id="policy_1",
            owner_id="owner_1",
            minimum_price_usdc=Decimal("2"),
            maximum_price_usdc=Decimal("1"),
        )
    except ContractError:
        pass
    else:
        raise AssertionError("inverted price bounds must fail")


def test_sku_serializes_decimal_as_string():
    sku = ServiceSKU(
        sku_id="sku_1",
        capability_id="cap_1",
        name="Verify",
        outcome="Return evidence",
        base_price_usdc=Decimal("0.10"),
    )
    assert sku.to_dict()["base_price_usdc"] == "0.1"


def test_confirmed_payment_requires_transaction_hash():
    try:
        PaymentReceipt(
            payment_id="payment_1",
            proposal_id="proposal_1",
            idempotency_key="idem_1",
            state=PaymentState.CONFIRMED,
            amount_usdc=Decimal("1"),
            chain="ARC-TESTNET",
            payer_wallet="payer",
            payee_wallet="payee",
        )
    except ContractError:
        pass
    else:
        raise AssertionError("confirmed payment without tx hash must fail")
