from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from autonomerce.payments.arc_rpc_lookup import (  # noqa: E402
    ARC_TESTNET_CHAIN_ID_HEX,
    ARC_TESTNET_RPC_URL,
    ARC_TESTNET_USDC,
    ERC20_TRANSFER_TOPIC,
    ArcRPCLookupError,
    ArcTestnetRPCClient,
    arc_testnet_transaction_lookup_factory,
)
from autonomerce.payments.api_adapter import _load_transaction_lookup  # noqa: E402


PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
TX_HASH = "0x" + ("a" * 64)
BLOCK_HASH = "0x" + ("b" * 64)


def _topic(address: str) -> str:
    return "0x" + ("0" * 24) + address[2:].lower()


def _quantity_word(value: int) -> str:
    return f"0x{value:064x}"


def _rpc_results() -> dict[str, Any]:
    transfer_log = {
        "address": ARC_TESTNET_USDC,
        "topics": [ERC20_TRANSFER_TOPIC, _topic(PAYER), _topic(PAYEE)],
        "data": _quantity_word(100_000),
        "blockNumber": "0x10",
        "transactionHash": TX_HASH,
        "removed": False,
    }
    return {
        "eth_chainId": ARC_TESTNET_CHAIN_ID_HEX,
        "eth_getTransactionByHash": {
            "hash": TX_HASH,
            "chainId": ARC_TESTNET_CHAIN_ID_HEX,
            "blockNumber": "0x10",
            "blockHash": BLOCK_HASH,
        },
        "eth_getTransactionReceipt": {
            "transactionHash": TX_HASH,
            "blockNumber": "0x10",
            "blockHash": BLOCK_HASH,
            "status": "0x1",
            "logs": [transfer_log],
        },
        "eth_blockNumber": "0x10",
    }


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        url: str = ARC_TESTNET_RPC_URL,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.url = url
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


class FakeOpener:
    def __init__(
        self,
        results: dict[str, Any] | None = None,
        *,
        response_factory: Any = None,
        exception: Exception | None = None,
    ) -> None:
        self.results = results or _rpc_results()
        self.response_factory = response_factory
        self.exception = exception
        self.calls: list[dict[str, Any]] = []

    def open(self, request, *, timeout: int):
        if self.exception is not None:
            raise self.exception
        assert request.full_url == ARC_TESTNET_RPC_URL
        payload = json.loads(request.data.decode("ascii"))
        self.calls.append(
            {
                "payload": payload,
                "timeout": timeout,
                "headers": dict(request.header_items()),
            }
        )
        if self.response_factory is not None:
            return self.response_factory(payload)
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": self.results[payload["method"]],
            },
            separators=(",", ":"),
        ).encode()
        return FakeResponse(body)


def test_arc_lookup_returns_exact_transaction_hook_mapping():
    opener = FakeOpener()
    evidence = ArcTestnetRPCClient(opener=opener).lookup(TX_HASH.upper().replace("X", "x"))

    assert evidence == {
        "confirmed": True,
        "chain": "ARC-TESTNET",
        "amountUsdc": "0.1",
        "payerWallet": PAYER,
        "payeeWallet": PAYEE,
        "transactionHash": TX_HASH,
        "token": "USDC",
        "asset": ARC_TESTNET_USDC,
    }
    assert [call["payload"]["method"] for call in opener.calls] == [
        "eth_chainId",
        "eth_getTransactionByHash",
        "eth_getTransactionReceipt",
        "eth_blockNumber",
    ]
    assert all(call["timeout"] == 10 for call in opener.calls)
    assert all(
        call["headers"]["Content-type"] == "application/json"
        for call in opener.calls
    )


def test_factory_accepts_adapter_environment_and_returns_callable(monkeypatch):
    monkeypatch.setattr(
        "autonomerce.payments.arc_rpc_lookup.build_opener",
        lambda *handlers: FakeOpener(),
    )
    lookup = arc_testnet_transaction_lookup_factory(
        environment={"AUTONOMERCE_MODE": "live"}
    )
    assert callable(lookup)
    assert lookup(TX_HASH)["confirmed"] is True


def test_factory_loads_through_autonomerce_environment_contract(monkeypatch):
    monkeypatch.setattr(
        "autonomerce.payments.arc_rpc_lookup.build_opener",
        lambda *handlers: FakeOpener(),
    )
    lookup = _load_transaction_lookup(
        {
            "AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY": (
                "autonomerce.payments.arc_rpc_lookup:"
                "arc_testnet_transaction_lookup_factory"
            )
        }
    )
    assert lookup(TX_HASH)["asset"] == ARC_TESTNET_USDC


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda results: results.__setitem__("eth_chainId", "0x1"),
            "wrong chain ID",
        ),
        (
            lambda results: results["eth_getTransactionByHash"].__setitem__(
                "chainId", "0x1"
            ),
            "wrong chain",
        ),
        (
            lambda results: results["eth_getTransactionReceipt"].__setitem__(
                "status", "0x0"
            ),
            "not successful",
        ),
        (
            lambda results: results.__setitem__("eth_blockNumber", "0xf"),
            "one confirmation",
        ),
        (
            lambda results: results["eth_getTransactionReceipt"].__setitem__(
                "blockNumber", None
            ),
            "canonical hex quantity",
        ),
    ],
)
def test_arc_lookup_rejects_wrong_chain_failed_or_unconfirmed_receipt(
    mutation, message
):
    results = _rpc_results()
    mutation(results)
    with pytest.raises(ArcRPCLookupError, match=message):
        ArcTestnetRPCClient(opener=FakeOpener(results)).lookup(TX_HASH)


def test_arc_lookup_rejects_wrong_usdc_contract():
    results = _rpc_results()
    results["eth_getTransactionReceipt"]["logs"][0]["address"] = PAYER

    with pytest.raises(ArcRPCLookupError, match="exactly one canonical"):
        ArcTestnetRPCClient(opener=FakeOpener(results)).lookup(TX_HASH)


def test_arc_lookup_rejects_duplicate_canonical_transfer_logs():
    results = _rpc_results()
    original = results["eth_getTransactionReceipt"]["logs"][0]
    results["eth_getTransactionReceipt"]["logs"].append(dict(original))

    with pytest.raises(ArcRPCLookupError, match="exactly one canonical"):
        ArcTestnetRPCClient(opener=FakeOpener(results)).lookup(TX_HASH)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda log: log.__setitem__("removed", True),
        lambda log: log.__setitem__("transactionHash", "0x" + ("c" * 64)),
        lambda log: log.__setitem__("blockNumber", "0x11"),
        lambda log: log.__setitem__("topics", log["topics"][:2]),
        lambda log: log["topics"].__setitem__(1, "0x" + ("1" * 64)),
        lambda log: log.__setitem__("data", "0x186a0"),
        lambda log: log.__setitem__("data", _quantity_word(0)),
    ],
)
def test_arc_lookup_rejects_malformed_or_ambiguous_transfer_log(mutation):
    results = _rpc_results()
    mutation(results["eth_getTransactionReceipt"]["logs"][0])

    with pytest.raises(ArcRPCLookupError):
        ArcTestnetRPCClient(opener=FakeOpener(results)).lookup(TX_HASH)


@pytest.mark.parametrize(
    ("response_factory", "message"),
    [
        (
            lambda payload: FakeResponse(b"{not-json"),
            "malformed JSON",
        ),
        (
            lambda payload: FakeResponse(
                (
                    '{"jsonrpc":"2.0","id":'
                    f'{payload["id"]},"result":NaN}}'
                ).encode()
            ),
            "invalid constant",
        ),
        (
            lambda payload: FakeResponse(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "error": {"code": -32000, "message": "failed"},
                    }
                ).encode()
            ),
            "only jsonrpc, id, and result",
        ),
        (
            lambda payload: FakeResponse(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": payload["id"] + 1,
                        "result": ARC_TESTNET_CHAIN_ID_HEX,
                    }
                ).encode()
            ),
            "does not match request",
        ),
        (
            lambda payload: FakeResponse(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": ARC_TESTNET_CHAIN_ID_HEX,
                    }
                ).encode(),
                url="https://redirected.example/rpc",
            ),
            "response URL changed",
        ),
    ],
)
def test_arc_lookup_rejects_malformed_rpc_errors_and_redirects(
    response_factory, message
):
    with pytest.raises(ArcRPCLookupError, match=message):
        ArcTestnetRPCClient(
            opener=FakeOpener(response_factory=response_factory)
        ).lookup(TX_HASH)


def test_arc_lookup_rejects_oversized_body_and_declared_content_length():
    oversized = FakeOpener(
        response_factory=lambda payload: FakeResponse(b"x" * 1025)
    )
    with pytest.raises(ArcRPCLookupError, match="size cap"):
        ArcTestnetRPCClient(
            opener=oversized,
            max_response_bytes=1024,
        ).lookup(TX_HASH)

    declared = FakeOpener(
        response_factory=lambda payload: FakeResponse(
            b"{}",
            headers={"Content-Length": "1025"},
        )
    )
    with pytest.raises(ArcRPCLookupError, match="size cap"):
        ArcTestnetRPCClient(
            opener=declared,
            max_response_bytes=1024,
        ).lookup(TX_HASH)


def test_arc_lookup_rejects_http_errors_and_duplicate_json_keys():
    error = HTTPError(
        ARC_TESTNET_RPC_URL,
        503,
        "unavailable",
        {},
        None,
    )
    with pytest.raises(ArcRPCLookupError, match="HTTP error"):
        ArcTestnetRPCClient(opener=FakeOpener(exception=error)).lookup(TX_HASH)

    duplicate = FakeOpener(
        response_factory=lambda payload: FakeResponse(
            (
                '{"jsonrpc":"2.0","id":1,"result":"0x4cef52",'
                '"result":"0x4cef52"}'
            ).encode()
        )
    )
    with pytest.raises(ArcRPCLookupError, match="duplicate object keys"):
        ArcTestnetRPCClient(opener=duplicate).lookup(TX_HASH)
