from __future__ import annotations

import ast
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    PROJECT_ROOT
    / "evidence"
    / "templates"
    / "okf"
    / "external-testnet-microdeal.public.schema.json"
)
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_external_testnet_microdeal.py"


def _public_evidence_literal_keys() -> set[str]:
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "_public_evidence":
            continue
        for nested in ast.walk(node):
            if not isinstance(nested, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "evidence"
                for target in nested.targets
            ):
                continue
            if not isinstance(nested.value, ast.Dict):
                continue
            keys = {
                key.value
                for key in nested.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if keys:
                return keys
    raise AssertionError("_public_evidence literal was not found")


def test_external_microdeal_public_schema_tracks_runner_field_set():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    required = set(schema["required"])
    properties = set(schema["properties"])
    runner_fields = _public_evidence_literal_keys()

    assert schema["additionalProperties"] is False
    assert required == properties
    assert required == runner_fields


def test_external_microdeal_public_schema_preserves_claim_boundaries():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = schema["properties"]

    assert properties["network"]["const"] == "ARC-TESTNET"
    assert properties["token"]["const"] == "USDC"
    assert (
        properties["asset"]["const"]
        == "0x3600000000000000000000000000000000000000"
    )
    assert properties["amountUsdc"]["const"] == "0.1"
    assert properties["synthetic"]["const"] is False
    assert properties["movesFunds"]["const"] is True
    assert properties["fundingSource"]["const"] == "founder_sponsored_testnet"
    assert properties["countedAsRevenue"]["const"] is False
    assert properties["payingCustomer"]["const"] is False
    assert properties["payerWallet"]["type"] == "null"
    assert properties["payeeWallet"]["type"] == "null"
    assert properties["customerConsentToPublish"]["const"] is True
    assert properties["independentLookupVerified"]["const"] is True
    assert properties["idempotentReplayVerified"]["const"] is True
