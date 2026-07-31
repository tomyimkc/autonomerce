"""Independent, fail-closed Arc testnet transaction lookup.

The factory in this module is suitable for
``AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY``.  It performs read-only JSON-RPC
requests with Python's standard library and derives payment evidence from one
canonical USDC ``Transfer`` log rather than trusting Circle CLI output.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
import json
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    Request,
    build_opener,
)

from autonomerce.contracts import usdc_text

from .models import normalize_transaction_hash


ARC_TESTNET_RPC_URL = "https://rpc.testnet.arc.network"
ARC_TESTNET_EXPLORER_URL = "https://testnet.arcscan.app"
ARC_TESTNET_CHAIN = "ARC-TESTNET"
ARC_TESTNET_CHAIN_ID = 5_042_002
ARC_TESTNET_CHAIN_ID_HEX = "0x4cef52"
ARC_TESTNET_USDC = "0x3600000000000000000000000000000000000000"
ERC20_TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)
USDC_DECIMALS = 6
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024

_HEX_QUANTITY = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
_HEX_32_BYTES = re.compile(r"^0x[0-9a-fA-F]{64}$")
_TOPIC_ADDRESS = re.compile(r"^0x0{24}([0-9a-fA-F]{40})$")


class ArcRPCLookupError(RuntimeError):
    """Arc RPC evidence was absent, unsafe, malformed, or inconsistent."""


class _Response(Protocol):
    headers: Mapping[str, str]

    def __enter__(self) -> "_Response":
        raise NotImplementedError

    def __exit__(self, *args: object) -> None:
        raise NotImplementedError

    def getcode(self) -> int:
        raise NotImplementedError

    def geturl(self) -> str:
        raise NotImplementedError

    def read(self, amount: int = -1) -> bytes:
        raise NotImplementedError


class _Opener(Protocol):
    def open(self, request: Request, *, timeout: int) -> _Response:
        raise NotImplementedError


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise ArcRPCLookupError("Arc RPC redirects are forbidden")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArcRPCLookupError("Arc RPC JSON contains duplicate object keys")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ArcRPCLookupError(f"Arc RPC JSON contains invalid constant {value}")


def _hex_quantity(value: object, *, field_name: str) -> int:
    if not isinstance(value, str) or not _HEX_QUANTITY.fullmatch(value):
        raise ArcRPCLookupError(f"{field_name} is not a canonical hex quantity")
    return int(value, 16)


def _hash32(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _HEX_32_BYTES.fullmatch(value):
        raise ArcRPCLookupError(f"{field_name} is not a 32-byte hex value")
    return value.lower()


def _uint256_word(value: object, *, field_name: str) -> int:
    if not isinstance(value, str) or not _HEX_32_BYTES.fullmatch(value):
        raise ArcRPCLookupError(f"{field_name} is not a 32-byte ABI word")
    return int(value, 16)


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArcRPCLookupError(f"{field_name} must be an object")
    return value


def _address_from_topic(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ArcRPCLookupError(f"{field_name} must be a topic string")
    match = _TOPIC_ADDRESS.fullmatch(value)
    if match is None:
        raise ArcRPCLookupError(f"{field_name} is not a canonical address topic")
    address = f"0x{match.group(1)}"
    if address == "0x" + ("0" * 40):
        raise ArcRPCLookupError(f"{field_name} contains the zero address")
    return address.lower()


class ArcTestnetRPCClient:
    """Read and validate one Arc testnet USDC settlement."""

    def __init__(
        self,
        *,
        opener: _Opener | OpenerDirector | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 30
        ):
            raise ValueError("Arc RPC timeout must be an integer from 1 to 30")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1024 <= max_response_bytes <= 1024 * 1024
        ):
            raise ValueError(
                "Arc RPC response cap must be an integer from 1024 to 1048576"
            )
        self.opener = opener or build_opener(_RejectRedirects())
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def _rpc(
        self,
        method: str,
        params: list[object],
        *,
        request_id: int,
    ) -> object:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        request = Request(
            ARC_TESTNET_RPC_URL,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "autonomerce-arc-proof/1",
            },
            method="POST",
        )
        try:
            with self.opener.open(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                if response.getcode() != 200:
                    raise ArcRPCLookupError("Arc RPC returned a non-200 response")
                if response.geturl() != ARC_TESTNET_RPC_URL:
                    raise ArcRPCLookupError("Arc RPC response URL changed")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length, 10)
                    except (TypeError, ValueError) as exc:
                        raise ArcRPCLookupError(
                            "Arc RPC Content-Length is malformed"
                        ) from exc
                    if (
                        declared_length < 0
                        or declared_length > self.max_response_bytes
                    ):
                        raise ArcRPCLookupError(
                            "Arc RPC response exceeds the configured size cap"
                        )
                raw = response.read(self.max_response_bytes + 1)
        except ArcRPCLookupError:
            raise
        except HTTPError as exc:
            raise ArcRPCLookupError("Arc RPC returned an HTTP error") from exc
        except URLError as exc:
            raise ArcRPCLookupError("Arc RPC network request failed") from exc
        except (OSError, TimeoutError) as exc:
            raise ArcRPCLookupError("Arc RPC request could not complete") from exc
        if not isinstance(raw, bytes):
            raise ArcRPCLookupError("Arc RPC response body must be bytes")
        if len(raw) > self.max_response_bytes:
            raise ArcRPCLookupError(
                "Arc RPC response exceeds the configured size cap"
            )
        try:
            text = raw.decode("utf-8", errors="strict")
            payload = json.loads(
                text,
                parse_float=Decimal,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except ArcRPCLookupError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ArcRPCLookupError("Arc RPC returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise ArcRPCLookupError("Arc RPC response must be a JSON object")
        if set(payload) != {"jsonrpc", "id", "result"}:
            raise ArcRPCLookupError(
                "Arc RPC response must contain only jsonrpc, id, and result"
            )
        if payload["jsonrpc"] != "2.0" or payload["id"] != request_id:
            raise ArcRPCLookupError("Arc RPC response envelope does not match request")
        return payload["result"]

    def lookup(self, transaction_hash: str) -> Mapping[str, Any]:
        requested_hash = normalize_transaction_hash(transaction_hash).lower()
        chain_id = _hex_quantity(
            self._rpc("eth_chainId", [], request_id=1),
            field_name="eth_chainId result",
        )
        if chain_id != ARC_TESTNET_CHAIN_ID:
            raise ArcRPCLookupError("Arc RPC reported the wrong chain ID")

        transaction = _mapping(
            self._rpc(
                "eth_getTransactionByHash",
                [requested_hash],
                request_id=2,
            ),
            field_name="transaction",
        )
        receipt = _mapping(
            self._rpc(
                "eth_getTransactionReceipt",
                [requested_hash],
                request_id=3,
            ),
            field_name="receipt",
        )
        latest_block = _hex_quantity(
            self._rpc("eth_blockNumber", [], request_id=4),
            field_name="latest block",
        )

        transaction_hash_value = _hash32(
            transaction.get("hash"),
            field_name="transaction hash",
        )
        receipt_hash_value = _hash32(
            receipt.get("transactionHash"),
            field_name="receipt transaction hash",
        )
        if (
            transaction_hash_value != requested_hash
            or receipt_hash_value != requested_hash
        ):
            raise ArcRPCLookupError("Arc RPC returned the wrong transaction")
        if "chainId" in transaction:
            transaction_chain_id = _hex_quantity(
                transaction.get("chainId"),
                field_name="transaction chain ID",
            )
            if transaction_chain_id != ARC_TESTNET_CHAIN_ID:
                raise ArcRPCLookupError("transaction belongs to the wrong chain")

        transaction_block = _hex_quantity(
            transaction.get("blockNumber"),
            field_name="transaction block number",
        )
        receipt_block = _hex_quantity(
            receipt.get("blockNumber"),
            field_name="receipt block number",
        )
        if transaction_block != receipt_block:
            raise ArcRPCLookupError("transaction and receipt block numbers differ")
        transaction_block_hash = _hash32(
            transaction.get("blockHash"),
            field_name="transaction block hash",
        )
        receipt_block_hash = _hash32(
            receipt.get("blockHash"),
            field_name="receipt block hash",
        )
        if transaction_block_hash != receipt_block_hash:
            raise ArcRPCLookupError("transaction and receipt block hashes differ")
        if _hex_quantity(receipt.get("status"), field_name="receipt status") != 1:
            raise ArcRPCLookupError("Arc receipt status is not successful")
        confirmations = latest_block - receipt_block + 1
        if confirmations < 1:
            raise ArcRPCLookupError("Arc receipt does not have one confirmation")

        logs = receipt.get("logs")
        if not isinstance(logs, list):
            raise ArcRPCLookupError("Arc receipt logs must be an array")
        matching_logs: list[Mapping[str, Any]] = []
        for raw_log in logs:
            log = _mapping(raw_log, field_name="receipt log")
            address = log.get("address")
            topics = log.get("topics")
            if (
                isinstance(address, str)
                and address.lower() == ARC_TESTNET_USDC
                and isinstance(topics, list)
                and topics
                and isinstance(topics[0], str)
                and topics[0].lower() == ERC20_TRANSFER_TOPIC
            ):
                matching_logs.append(log)
        if len(matching_logs) != 1:
            raise ArcRPCLookupError(
                "Arc receipt must contain exactly one canonical USDC Transfer log"
            )

        transfer = matching_logs[0]
        if transfer.get("removed") is not False:
            raise ArcRPCLookupError("canonical USDC Transfer log is removed or ambiguous")
        if (
            _hash32(
                transfer.get("transactionHash"),
                field_name="Transfer transaction hash",
            )
            != requested_hash
        ):
            raise ArcRPCLookupError("Transfer log belongs to the wrong transaction")
        if (
            _hex_quantity(
                transfer.get("blockNumber"),
                field_name="Transfer block number",
            )
            != receipt_block
        ):
            raise ArcRPCLookupError("Transfer log belongs to the wrong block")
        topics = transfer.get("topics")
        if not isinstance(topics, list) or len(topics) != 3:
            raise ArcRPCLookupError(
                "canonical USDC Transfer log must contain exactly three topics"
            )
        if (
            not isinstance(topics[0], str)
            or topics[0].lower() != ERC20_TRANSFER_TOPIC
        ):
            raise ArcRPCLookupError("canonical USDC Transfer signature is invalid")
        payer = _address_from_topic(topics[1], field_name="Transfer payer")
        payee = _address_from_topic(topics[2], field_name="Transfer payee")
        raw_amount = _uint256_word(
            transfer.get("data"),
            field_name="Transfer amount",
        )
        if raw_amount <= 0:
            raise ArcRPCLookupError("USDC Transfer amount must be positive")
        amount = Decimal(raw_amount) / (Decimal(10) ** USDC_DECIMALS)

        return {
            "confirmed": True,
            "chain": ARC_TESTNET_CHAIN,
            "amountUsdc": usdc_text(amount),
            "payerWallet": payer,
            "payeeWallet": payee,
            "transactionHash": requested_hash,
            "token": "USDC",
            "asset": ARC_TESTNET_USDC,
        }


def arc_testnet_transaction_lookup_factory(
    *,
    environment: Mapping[str, str] | None = None,
) -> Callable[[str], Mapping[str, Any]]:
    """Return the independent lookup callable expected by the payment adapter.

    ``environment`` is accepted for factory-loader compatibility but intentionally
    ignored: this implementation is pinned to the official Arc testnet endpoint,
    chain ID, explorer, and canonical USDC contract.
    """

    del environment
    return ArcTestnetRPCClient().lookup


build_arc_testnet_transaction_lookup = arc_testnet_transaction_lookup_factory


__all__ = [
    "ARC_TESTNET_CHAIN",
    "ARC_TESTNET_CHAIN_ID",
    "ARC_TESTNET_CHAIN_ID_HEX",
    "ARC_TESTNET_EXPLORER_URL",
    "ARC_TESTNET_RPC_URL",
    "ARC_TESTNET_USDC",
    "ArcRPCLookupError",
    "ArcTestnetRPCClient",
    "ERC20_TRANSFER_TOPIC",
    "arc_testnet_transaction_lookup_factory",
    "build_arc_testnet_transaction_lookup",
]
