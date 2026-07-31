"""Durable single-node SQLite repository for the Autonomerce commerce aggregate.

The repository intentionally supports one application process only. SQLite provides
the durable transaction boundary, while an advisory lock prevents a second API
process from relying on process-local request locks against the same commerce file.

When the guarded payment adapter uses the same SQLite file, startup also reconciles
confirmed rows from its ``payments`` table. This closes the process-crash window
between durable payment confirmation and the API commerce projection without
automatically retrying ambiguous ``SUBMITTING`` payments.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import json
import os
from pathlib import Path
import shlex
import sqlite3
from statistics import median
from threading import RLock
from typing import Any, Iterator, Mapping

from autonomerce.contracts import (
    BuyerNeed,
    CapabilityDescriptor,
    CommercialPolicy,
    FulfillmentReceipt,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ProposalState,
    ServiceSKU,
    usdc_text,
)

from .repository import (
    ProspectRecord,
    ReceiptPublication,
    RepositoryDurability,
    SettlementAuthorization,
    monotonic_proposal,
    payment_matches_settlement_authorization,
)

try:
    import fcntl
except ImportError as exc:  # pragma: no cover - deployment targets POSIX hosts.
    raise RuntimeError(
        "SQLiteRepository requires POSIX advisory file locking"
    ) from exc


_SCHEMA_VERSION = "1"
_POST_ACCEPTANCE_STATES = {
    ProposalState.ACCEPTED,
    ProposalState.PAID,
    ProposalState.FULFILLING,
    ProposalState.DELIVERED,
    ProposalState.FAILED,
}
_PROCESS_LOCK_REGISTRY: dict[str, dict[str, Any]] = {}
_PROCESS_LOCK_REGISTRY_GUARD = RLock()


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_load(value: str) -> Any:
    return json.loads(value)


def _capability_payload(value: CapabilityDescriptor) -> dict[str, Any]:
    return {
        "capability_id": value.capability_id,
        "name": value.name,
        "description": value.description,
        "input_schema": dict(value.input_schema),
        "output_schema": dict(value.output_schema),
        "source_kind": value.source_kind,
        "source_url": value.source_url,
        "tags": list(value.tags),
    }


def _capability_from_payload(value: Mapping[str, Any]) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=str(value["capability_id"]),
        name=str(value["name"]),
        description=str(value["description"]),
        input_schema=dict(value.get("input_schema", {})),
        output_schema=dict(value.get("output_schema", {})),
        source_kind=str(value.get("source_kind", "manual")),
        source_url=(
            str(value["source_url"]) if value.get("source_url") is not None else None
        ),
        tags=tuple(value.get("tags", ())),
    )


def _sku_payload(value: ServiceSKU) -> dict[str, Any]:
    return {
        "sku_id": value.sku_id,
        "capability_id": value.capability_id,
        "name": value.name,
        "outcome": value.outcome,
        "base_price_usdc": usdc_text(value.base_price_usdc),
        "input_schema": dict(value.input_schema),
        "output_schema": dict(value.output_schema),
        "acceptance_criteria": list(value.acceptance_criteria),
        "maximum_latency_seconds": value.maximum_latency_seconds,
        "capacity_per_hour": value.capacity_per_hour,
    }


def _sku_from_payload(value: Mapping[str, Any]) -> ServiceSKU:
    return ServiceSKU(
        sku_id=str(value["sku_id"]),
        capability_id=str(value["capability_id"]),
        name=str(value["name"]),
        outcome=str(value["outcome"]),
        base_price_usdc=Decimal(str(value["base_price_usdc"])),
        input_schema=dict(value.get("input_schema", {})),
        output_schema=dict(value.get("output_schema", {})),
        acceptance_criteria=tuple(value.get("acceptance_criteria", ())),
        maximum_latency_seconds=int(value.get("maximum_latency_seconds", 300)),
        capacity_per_hour=int(value.get("capacity_per_hour", 1)),
    )


def _policy_payload(value: CommercialPolicy) -> dict[str, Any]:
    return {
        "policy_id": value.policy_id,
        "owner_id": value.owner_id,
        "minimum_price_usdc": usdc_text(value.minimum_price_usdc),
        "maximum_price_usdc": usdc_text(value.maximum_price_usdc),
        "maximum_discount_fraction": format(
            value.maximum_discount_fraction, "f"
        ),
        "maximum_open_proposals": value.maximum_open_proposals,
        "maximum_tasks_per_hour": value.maximum_tasks_per_hour,
        "allowed_buyer_hosts": list(value.allowed_buyer_hosts),
        "blocked_buyer_hosts": list(value.blocked_buyer_hosts),
        "allowed_chains": list(value.allowed_chains),
        "allowed_token": value.allowed_token,
        "unattended": value.unattended,
    }


def _policy_from_payload(value: Mapping[str, Any]) -> CommercialPolicy:
    return CommercialPolicy(
        policy_id=str(value["policy_id"]),
        owner_id=str(value["owner_id"]),
        minimum_price_usdc=Decimal(str(value["minimum_price_usdc"])),
        maximum_price_usdc=Decimal(str(value["maximum_price_usdc"])),
        maximum_discount_fraction=Decimal(
            str(value.get("maximum_discount_fraction", "0"))
        ),
        maximum_open_proposals=int(value.get("maximum_open_proposals", 10)),
        maximum_tasks_per_hour=int(value.get("maximum_tasks_per_hour", 20)),
        allowed_buyer_hosts=tuple(value.get("allowed_buyer_hosts", ())),
        blocked_buyer_hosts=tuple(value.get("blocked_buyer_hosts", ())),
        allowed_chains=tuple(value.get("allowed_chains", ())),
        allowed_token=str(value.get("allowed_token", "USDC")),
        unattended=bool(value.get("unattended", True)),
    )


def _prospect_payload(value: ProspectRecord) -> dict[str, Any]:
    need = value.need
    return {
        "need": {
            "need_id": need.need_id,
            "buyer_agent_url": need.buyer_agent_url,
            "desired_outcome": need.desired_outcome,
            "maximum_price_usdc": usdc_text(need.maximum_price_usdc),
            "required_tags": list(need.required_tags),
            "input_payload": dict(need.input_payload),
            "expires_at": need.expires_at,
        },
        "opted_in": value.opted_in,
        "owner_id": value.owner_id,
        "consent_reference": value.consent_reference,
    }


def _prospect_from_payload(value: Mapping[str, Any]) -> ProspectRecord:
    need = dict(value["need"])
    return ProspectRecord(
        need=BuyerNeed(
            need_id=str(need["need_id"]),
            buyer_agent_url=str(need["buyer_agent_url"]),
            desired_outcome=str(need["desired_outcome"]),
            maximum_price_usdc=Decimal(str(need["maximum_price_usdc"])),
            required_tags=tuple(need.get("required_tags", ())),
            input_payload=dict(need.get("input_payload", {})),
            expires_at=(
                str(need["expires_at"])
                if need.get("expires_at") is not None
                else None
            ),
        ),
        opted_in=bool(value["opted_in"]),
        owner_id=str(value["owner_id"]),
        consent_reference=str(value["consent_reference"]),
    )


def _proposal_payload(value: Proposal) -> dict[str, Any]:
    return {
        "proposal_id": value.proposal_id,
        "seller_agent_url": value.seller_agent_url,
        "buyer_agent_url": value.buyer_agent_url,
        "buyer_need_id": value.buyer_need_id,
        "sku_id": value.sku_id,
        "problem_observed": value.problem_observed,
        "offered_outcome": value.offered_outcome,
        "price_usdc": usdc_text(value.price_usdc),
        "delivery_seconds": value.delivery_seconds,
        "acceptance_criteria": list(value.acceptance_criteria),
        "expires_at": value.expires_at,
        "state": value.state.value,
        "revision": value.revision,
    }


def _proposal_from_payload(value: Mapping[str, Any]) -> Proposal:
    return Proposal(
        proposal_id=str(value["proposal_id"]),
        seller_agent_url=str(value["seller_agent_url"]),
        buyer_agent_url=str(value["buyer_agent_url"]),
        buyer_need_id=(
            str(value["buyer_need_id"])
            if value.get("buyer_need_id") is not None
            else None
        ),
        sku_id=str(value["sku_id"]),
        problem_observed=str(value.get("problem_observed", "")),
        offered_outcome=str(value["offered_outcome"]),
        price_usdc=Decimal(str(value["price_usdc"])),
        delivery_seconds=int(value["delivery_seconds"]),
        acceptance_criteria=tuple(value.get("acceptance_criteria", ())),
        expires_at=(
            str(value["expires_at"]) if value.get("expires_at") is not None else None
        ),
        state=ProposalState(str(value.get("state", ProposalState.DRAFT.value))),
        revision=int(value.get("revision", 1)),
    )


def _settlement_authorization_payload(
    value: SettlementAuthorization,
) -> dict[str, Any]:
    return {
        "authorization_id": value.authorization_id,
        "proposal_id": value.proposal_id,
        "proposal_revision": value.proposal_revision,
        "proposal_contract_hash": value.proposal_contract_hash,
        "amount_usdc": usdc_text(value.amount_usdc),
        "payer_wallet": value.payer_wallet,
        "payee_wallet": value.payee_wallet,
        "chain": value.chain,
        "token": value.token,
        "asset": value.asset,
        "commercial_policy_id": value.commercial_policy_id,
        "commercial_policy_version": value.commercial_policy_version,
        "seller_configuration_id": value.seller_configuration_id,
        "seller_configuration_version": value.seller_configuration_version,
        "expires_at": value.expires_at,
        "created_at": value.created_at,
    }


def _settlement_authorization_from_payload(
    value: Mapping[str, Any],
) -> SettlementAuthorization:
    return SettlementAuthorization(
        authorization_id=str(value["authorization_id"]),
        proposal_id=str(value["proposal_id"]),
        proposal_revision=int(value["proposal_revision"]),
        proposal_contract_hash=str(value["proposal_contract_hash"]),
        amount_usdc=Decimal(str(value["amount_usdc"])),
        payer_wallet=str(value["payer_wallet"]),
        payee_wallet=str(value["payee_wallet"]),
        chain=str(value["chain"]),
        token=str(value["token"]),
        asset=str(value["asset"]),
        commercial_policy_id=str(value["commercial_policy_id"]),
        commercial_policy_version=str(value["commercial_policy_version"]),
        seller_configuration_id=str(value["seller_configuration_id"]),
        seller_configuration_version=str(
            value["seller_configuration_version"]
        ),
        expires_at=str(value["expires_at"]),
        created_at=str(value["created_at"]),
    )


def _payment_payload(value: PaymentReceipt) -> dict[str, Any]:
    return {
        "payment_id": value.payment_id,
        "proposal_id": value.proposal_id,
        "idempotency_key": value.idempotency_key,
        "state": value.state.value,
        "amount_usdc": usdc_text(value.amount_usdc),
        "chain": value.chain,
        "token": value.token,
        "asset": value.asset,
        "payer_wallet": value.payer_wallet,
        "payee_wallet": value.payee_wallet,
        "transaction_hash": value.transaction_hash,
        "explorer_url": value.explorer_url,
        "confirmed_at": value.confirmed_at,
        "public": value.public,
    }


def _payment_from_payload(value: Mapping[str, Any]) -> PaymentReceipt:
    return PaymentReceipt(
        payment_id=str(value["payment_id"]),
        proposal_id=str(value["proposal_id"]),
        idempotency_key=str(value["idempotency_key"]),
        state=PaymentState(str(value["state"])),
        amount_usdc=Decimal(str(value["amount_usdc"])),
        chain=str(value["chain"]),
        token=str(value.get("token", "USDC")),
        asset=(
            str(value["asset"])
            if value.get("asset") is not None
            else None
        ),
        payer_wallet=str(value["payer_wallet"]),
        payee_wallet=str(value["payee_wallet"]),
        transaction_hash=(
            str(value["transaction_hash"])
            if value.get("transaction_hash") is not None
            else None
        ),
        explorer_url=(
            str(value["explorer_url"])
            if value.get("explorer_url") is not None
            else None
        ),
        confirmed_at=(
            str(value["confirmed_at"])
            if value.get("confirmed_at") is not None
            else None
        ),
        public=bool(value.get("public", False)),
    )


def _fulfillment_payload(value: FulfillmentReceipt) -> dict[str, Any]:
    return {
        "fulfillment_id": value.fulfillment_id,
        "proposal_id": value.proposal_id,
        "payment_id": value.payment_id,
        "seller_agent_url": value.seller_agent_url,
        "artifact_hash": value.artifact_hash,
        "accepted": value.accepted,
        "validator": value.validator,
        "acceptance_results": dict(value.acceptance_results),
        "delivered_at": value.delivered_at,
        "detail": dict(value.detail),
    }


def _fulfillment_from_payload(value: Mapping[str, Any]) -> FulfillmentReceipt:
    return FulfillmentReceipt(
        fulfillment_id=str(value["fulfillment_id"]),
        proposal_id=str(value["proposal_id"]),
        payment_id=str(value["payment_id"]),
        seller_agent_url=str(value["seller_agent_url"]),
        artifact_hash=str(value["artifact_hash"]),
        accepted=bool(value["accepted"]),
        validator=str(value["validator"]),
        acceptance_results=dict(value.get("acceptance_results", {})),
        delivered_at=(
            str(value["delivered_at"])
            if value.get("delivered_at") is not None
            else None
        ),
        detail=dict(value.get("detail", {})),
    )


def _publication_from_row(row: sqlite3.Row) -> ReceiptPublication:
    return ReceiptPublication(
        receipt_id=row["receipt_id"],
        proposal_id=row["proposal_id"],
        owner_id=row["owner_id"],
        approved_by=row["approved_by"],
        consent_reference=row["consent_reference"],
        fields=tuple(_json_load(row["fields_json"])),
        published_at=row["published_at"],
        version=int(row["version"]),
    )


def _configured_worker_count() -> tuple[str, int] | None:
    for name in (
        "AUTONOMERCE_API_WORKERS",
        "UVICORN_WORKERS",
        "WEB_CONCURRENCY",
        "GUNICORN_WORKERS",
    ):
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        try:
            count = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
        if count < 1:
            raise RuntimeError(f"{name} must be at least 1")
        if count > 1:
            return name, count

    for name in ("GUNICORN_CMD_ARGS", "UVICORN_CMD_ARGS"):
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        try:
            arguments = shlex.split(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} is not valid shell-style arguments") from exc
        for index, argument in enumerate(arguments):
            count_text: str | None = None
            if argument in {"--workers", "-w"} and index + 1 < len(arguments):
                count_text = arguments[index + 1]
            elif argument.startswith("--workers="):
                count_text = argument.split("=", 1)[1]
            if count_text is None:
                continue
            try:
                count = int(count_text)
            except ValueError as exc:
                raise RuntimeError(f"{name} contains an invalid worker count") from exc
            if count > 1:
                return name, count
    return None


@dataclass(frozen=True)
class _PaymentMapping:
    payment_id: str
    proposal_id: str
    idempotency_key: str
    transaction_hash_key: str | None


class SQLiteRepository:
    """Transactional durable repository for one API process on one node."""

    storage_name = "sqlite"
    durability = RepositoryDurability.SINGLE_NODE
    supports_multiple_workers = False

    def __init__(self, path: str | Path) -> None:
        worker_configuration = _configured_worker_count()
        if worker_configuration is not None:
            name, count = worker_configuration
            raise RuntimeError(
                "SQLiteRepository is single-node/single-worker only; "
                f"{name}={count} is not supported"
            )

        raw_path = str(path).strip()
        if (
            not raw_path
            or raw_path == ":memory:"
            or raw_path.startswith("file:")
            or "\x00" in raw_path
        ):
            raise ValueError(
                "SQLiteRepository requires a durable filesystem database path"
            )
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise ValueError("SQLiteRepository path must be absolute")
        candidate.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        self.path = str(candidate.resolve())
        self.lock_path = f"{self.path}.commerce.lock"
        self._thread_lock = RLock()
        self._closed = False
        self._owner_pid = os.getpid()
        self._lock_key = self.path
        self._acquire_process_lock()
        try:
            self._initialize()
            self._recover()
        except Exception:
            self.close()
            raise

    @property
    def is_durable(self) -> bool:
        return True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SQLiteRepository is closed")
        if os.getpid() != self._owner_pid:
            raise RuntimeError(
                "SQLiteRepository cannot be reused after fork; "
                "run exactly one API worker"
            )

    def _acquire_process_lock(self) -> None:
        with _PROCESS_LOCK_REGISTRY_GUARD:
            existing = _PROCESS_LOCK_REGISTRY.get(self._lock_key)
            if existing is not None and existing["pid"] == os.getpid():
                existing["references"] += 1
                return

            descriptor = os.open(
                self.lock_path,
                os.O_RDWR | os.O_CREAT,
                0o600,
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                os.close(descriptor)
                raise RuntimeError(
                    "SQLiteRepository database is already owned by another "
                    "process; multiple API workers are not supported"
                ) from exc
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(descriptor)
            _PROCESS_LOCK_REGISTRY[self._lock_key] = {
                "descriptor": descriptor,
                "pid": os.getpid(),
                "references": 1,
            }

    def _connect_unchecked(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _connect(self) -> sqlite3.Connection:
        self._ensure_open()
        return self._connect_unchecked()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._thread_lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._thread_lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _initialize(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS commerce_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_sellers (
                seller_id TEXT PRIMARY KEY,
                agent_url TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_commerce_sellers_agent_url
            ON commerce_sellers(agent_url)
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_capabilities (
                capability_id TEXT PRIMARY KEY,
                seller_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(seller_id)
                    REFERENCES commerce_sellers(seller_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_commerce_capabilities_seller
            ON commerce_capabilities(seller_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_skus (
                sku_id TEXT PRIMARY KEY,
                seller_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(seller_id)
                    REFERENCES commerce_sellers(seller_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(capability_id)
                    REFERENCES commerce_capabilities(capability_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_commerce_skus_seller
            ON commerce_skus(seller_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_policies (
                seller_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(seller_id)
                    REFERENCES commerce_sellers(seller_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_prospects (
                need_id TEXT PRIMARY KEY,
                buyer_agent_url TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_commerce_prospects_buyer_url
            ON commerce_prospects(buyer_agent_url)
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_proposals (
                proposal_id TEXT PRIMARY KEY,
                seller_agent_url TEXT NOT NULL,
                sku_id TEXT NOT NULL,
                state TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                contract_hash TEXT,
                accepted INTEGER NOT NULL DEFAULT 0
                    CHECK(accepted IN (0, 1)),
                payload_json TEXT NOT NULL,
                FOREIGN KEY(sku_id)
                    REFERENCES commerce_skus(sku_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_commerce_proposals_owner
            ON commerce_proposals(owner_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_commerce_proposals_seller_url
            ON commerce_proposals(seller_agent_url)
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_settlement_authorizations (
                proposal_id TEXT PRIMARY KEY,
                authorization_id TEXT NOT NULL UNIQUE,
                proposal_revision INTEGER NOT NULL
                    CHECK(proposal_revision >= 1),
                proposal_contract_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(proposal_id)
                    REFERENCES commerce_proposals(proposal_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_payments (
                payment_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL UNIQUE,
                transaction_hash_key TEXT UNIQUE,
                state TEXT NOT NULL,
                mocked INTEGER NOT NULL CHECK(mocked IN (0, 1)),
                payload_json TEXT NOT NULL,
                FOREIGN KEY(proposal_id)
                    REFERENCES commerce_proposals(proposal_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_fulfillments (
                fulfillment_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE,
                payment_id TEXT NOT NULL UNIQUE,
                accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
                payload_json TEXT NOT NULL,
                FOREIGN KEY(proposal_id)
                    REFERENCES commerce_proposals(proposal_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(payment_id)
                    REFERENCES commerce_payments(payment_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_receipt_publications (
                receipt_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE,
                owner_id TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                consent_reference TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                published_at TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version >= 1),
                FOREIGN KEY(proposal_id)
                    REFERENCES commerce_proposals(proposal_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_negotiation_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                delta_usdc TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS commerce_counters (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL CHECK(value >= 0)
            )
            """,
        )
        with self._thread_lock:
            connection = self._connect()
            try:
                journal_mode = connection.execute(
                    "PRAGMA journal_mode=WAL"
                ).fetchone()[0]
                if str(journal_mode).lower() != "wal":
                    raise RuntimeError("SQLite WAL mode could not be enabled")
                connection.execute("BEGIN IMMEDIATE")
                for statement in statements:
                    connection.execute(statement)
                row = connection.execute(
                    """
                    SELECT value FROM commerce_metadata
                    WHERE key = 'schema_version'
                    """
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO commerce_metadata(key, value)
                        VALUES ('schema_version', ?)
                        """,
                        (_SCHEMA_VERSION,),
                    )
                elif row["value"] != _SCHEMA_VERSION:
                    raise RuntimeError(
                        "unsupported commerce SQLite schema version: "
                        f"{row['value']}"
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _table_columns(
        connection: sqlite3.Connection, table: str
    ) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }

    @staticmethod
    def _payment_mapping(receipt: PaymentReceipt) -> _PaymentMapping:
        return _PaymentMapping(
            payment_id=receipt.payment_id,
            proposal_id=receipt.proposal_id,
            idempotency_key=receipt.idempotency_key,
            transaction_hash_key=(
                receipt.transaction_hash.lower()
                if receipt.transaction_hash is not None
                else None
            ),
        )

    @staticmethod
    def _set_proposal_state(
        connection: sqlite3.Connection,
        proposal_id: str,
        state: ProposalState,
    ) -> None:
        row = connection.execute(
            """
            SELECT payload_json, accepted
            FROM commerce_proposals
            WHERE proposal_id = ?
            """,
            (proposal_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"commerce projection references missing proposal {proposal_id}"
            )
        payload = dict(_json_load(row["payload_json"]))
        payload["state"] = state.value
        accepted = bool(row["accepted"]) or state in _POST_ACCEPTANCE_STATES
        connection.execute(
            """
            UPDATE commerce_proposals
            SET state = ?, accepted = ?, payload_json = ?
            WHERE proposal_id = ?
            """,
            (
                state.value,
                int(accepted),
                _json_dump(payload),
                proposal_id,
            ),
        )

    @classmethod
    def _insert_payment(
        cls,
        connection: sqlite3.Connection,
        receipt: PaymentReceipt,
        *,
        mocked: bool,
    ) -> None:
        mapping = cls._payment_mapping(receipt)
        connection.execute(
            """
            INSERT INTO commerce_payments (
                payment_id, proposal_id, idempotency_key,
                transaction_hash_key, state, mocked, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mapping.payment_id,
                mapping.proposal_id,
                mapping.idempotency_key,
                mapping.transaction_hash_key,
                receipt.state.value,
                int(mocked),
                _json_dump(_payment_payload(receipt)),
            ),
        )

    def _recover_confirmed_payment_store_rows(
        self, connection: sqlite3.Connection
    ) -> None:
        table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'payments'
            """
        ).fetchone()
        if table is None:
            return
        required_columns = {
            "payment_id",
            "proposal_id",
            "idempotency_key",
            "state",
            "amount_usdc",
            "chain",
            "token",
            "asset",
            "payer_wallet",
            "payee_wallet",
            "transaction_hash",
            "explorer_url",
            "confirmed_at",
        }
        columns = self._table_columns(connection, "payments")
        if not required_columns.issubset(columns):
            missing = sorted(required_columns - columns)
            raise RuntimeError(
                "payments table is not the supported SQLite payment store; "
                f"missing columns: {missing}"
            )

        rows = connection.execute(
            """
            SELECT payment_id, proposal_id, idempotency_key, state,
                   amount_usdc, chain, token, asset, payer_wallet, payee_wallet,
                   transaction_hash, explorer_url, confirmed_at
            FROM payments
            WHERE state = ?
            ORDER BY rowid
            """,
            (PaymentState.CONFIRMED.value,),
        ).fetchall()
        for row in rows:
            receipt = PaymentReceipt(
                payment_id=row["payment_id"],
                proposal_id=row["proposal_id"],
                idempotency_key=row["idempotency_key"],
                state=PaymentState.CONFIRMED,
                amount_usdc=Decimal(row["amount_usdc"]),
                chain=row["chain"],
                token=row["token"],
                asset=row["asset"],
                payer_wallet=row["payer_wallet"],
                payee_wallet=row["payee_wallet"],
                transaction_hash=row["transaction_hash"],
                explorer_url=row["explorer_url"],
                confirmed_at=row["confirmed_at"],
                public=False,
            )
            proposal = connection.execute(
                """
                SELECT state, contract_hash, payload_json
                FROM commerce_proposals
                WHERE proposal_id = ?
                """,
                (receipt.proposal_id,),
            ).fetchone()
            if proposal is None:
                raise RuntimeError(
                    "confirmed payment has no durable commerce proposal: "
                    f"{receipt.payment_id}"
                )
            current_state = ProposalState(proposal["state"])
            if current_state not in _POST_ACCEPTANCE_STATES:
                raise RuntimeError(
                    "confirmed payment is bound to a proposal that was not "
                    f"accepted: {receipt.proposal_id}"
                )
            proposal_value = _proposal_from_payload(
                _json_load(proposal["payload_json"])
            )
            authorization_row = connection.execute(
                """
                SELECT payload_json
                FROM commerce_settlement_authorizations
                WHERE proposal_id = ?
                """,
                (receipt.proposal_id,),
            ).fetchone()
            if authorization_row is None:
                raise RuntimeError(
                    "confirmed payment has no immutable settlement authorization: "
                    f"{receipt.payment_id}"
                )
            authorization = _settlement_authorization_from_payload(
                _json_load(authorization_row["payload_json"])
            )
            if (
                authorization.proposal_id != proposal_value.proposal_id
                or authorization.proposal_revision != proposal_value.revision
                or authorization.proposal_contract_hash
                != proposal["contract_hash"]
                or not payment_matches_settlement_authorization(
                    receipt, authorization
                )
            ):
                raise RuntimeError(
                    "confirmed payment does not match the immutable settlement "
                    f"authorization: {receipt.payment_id}"
                )

            existing = connection.execute(
                """
                SELECT * FROM commerce_payments
                WHERE payment_id = ? OR proposal_id = ? OR idempotency_key = ?
                """,
                (
                    receipt.payment_id,
                    receipt.proposal_id,
                    receipt.idempotency_key,
                ),
            ).fetchall()
            if existing:
                expected = self._payment_mapping(receipt)
                for candidate in existing:
                    actual = _PaymentMapping(
                        payment_id=candidate["payment_id"],
                        proposal_id=candidate["proposal_id"],
                        idempotency_key=candidate["idempotency_key"],
                        transaction_hash_key=candidate["transaction_hash_key"],
                    )
                    if actual != expected:
                        raise RuntimeError(
                            "confirmed payment conflicts with durable commerce "
                            f"idempotency mappings: {receipt.payment_id}"
                        )
                    existing_receipt = _payment_from_payload(
                        _json_load(candidate["payload_json"])
                    )
                    if existing_receipt != receipt:
                        raise RuntimeError(
                            "confirmed payment conflicts with durable commerce "
                            f"evidence: {receipt.payment_id}"
                        )
            else:
                self._insert_payment(connection, receipt, mocked=False)

            if current_state is ProposalState.ACCEPTED:
                self._set_proposal_state(
                    connection,
                    receipt.proposal_id,
                    ProposalState.PAID,
                )

    def _recover(self) -> None:
        with self._write() as connection:
            check = connection.execute("PRAGMA quick_check").fetchone()
            if check is None or check[0] != "ok":
                detail = check[0] if check is not None else "no result"
                raise RuntimeError(f"commerce SQLite integrity check failed: {detail}")

            self._recover_confirmed_payment_store_rows(connection)

            rows = connection.execute(
                """
                SELECT proposal_id, state, accepted
                FROM commerce_proposals
                """
            ).fetchall()
            for row in rows:
                state = ProposalState(row["state"])
                if state in _POST_ACCEPTANCE_STATES and not bool(row["accepted"]):
                    connection.execute(
                        """
                        UPDATE commerce_proposals
                        SET accepted = 1
                        WHERE proposal_id = ?
                        """,
                        (row["proposal_id"],),
                    )

            payments = connection.execute(
                """
                SELECT proposal_id FROM commerce_payments
                WHERE state = ?
                """,
                (PaymentState.CONFIRMED.value,),
            ).fetchall()
            for payment in payments:
                proposal = connection.execute(
                    """
                    SELECT state FROM commerce_proposals
                    WHERE proposal_id = ?
                    """,
                    (payment["proposal_id"],),
                ).fetchone()
                if proposal is not None and ProposalState(
                    proposal["state"]
                ) is ProposalState.ACCEPTED:
                    self._set_proposal_state(
                        connection,
                        payment["proposal_id"],
                        ProposalState.PAID,
                    )

            fulfillments = connection.execute(
                """
                SELECT proposal_id, accepted
                FROM commerce_fulfillments
                """
            ).fetchall()
            for fulfillment in fulfillments:
                expected = (
                    ProposalState.DELIVERED
                    if bool(fulfillment["accepted"])
                    else ProposalState.FAILED
                )
                proposal = connection.execute(
                    """
                    SELECT state FROM commerce_proposals
                    WHERE proposal_id = ?
                    """,
                    (fulfillment["proposal_id"],),
                ).fetchone()
                if proposal is None or ProposalState(proposal["state"]) is not expected:
                    self._set_proposal_state(
                        connection,
                        fulfillment["proposal_id"],
                        expected,
                    )

    def close(self) -> None:
        if self._closed:
            return
        if os.getpid() == self._owner_pid:
            try:
                with self._thread_lock:
                    connection = self._connect_unchecked()
                    try:
                        connection.execute("PRAGMA wal_checkpoint(FULL)")
                    finally:
                        connection.close()
            except sqlite3.Error:
                pass
        self._closed = True

        with _PROCESS_LOCK_REGISTRY_GUARD:
            entry = _PROCESS_LOCK_REGISTRY.get(self._lock_key)
            if entry is None:
                return
            if entry["pid"] != os.getpid():
                try:
                    os.close(entry["descriptor"])
                except OSError:
                    pass
                return
            entry["references"] -= 1
            if entry["references"] > 0:
                return
            descriptor = entry["descriptor"]
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
                _PROCESS_LOCK_REGISTRY.pop(self._lock_key, None)

    def __enter__(self) -> "SQLiteRepository":
        self._ensure_open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def save_seller(
        self, seller: dict[str, Any], *, owner_id: str = "offline-demo"
    ) -> dict[str, Any]:
        seller_id = str(seller["seller_id"])
        payload = dict(seller)
        with self._write() as connection:
            existing = connection.execute(
                """
                SELECT owner_id FROM commerce_sellers
                WHERE seller_id = ?
                """,
                (seller_id,),
            ).fetchone()
            if existing is not None and existing["owner_id"] != owner_id:
                raise ValueError("seller owner cannot be changed")
            connection.execute(
                """
                INSERT INTO commerce_sellers(
                    seller_id, agent_url, owner_id, payload_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(seller_id) DO UPDATE SET
                    agent_url = excluded.agent_url,
                    payload_json = excluded.payload_json
                """,
                (
                    seller_id,
                    str(seller["agent_url"]),
                    owner_id,
                    _json_dump(payload),
                ),
            )
        return dict(payload)

    def get_seller(self, seller_id: str) -> dict[str, Any] | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_sellers
                WHERE seller_id = ?
                """,
                (seller_id,),
            ).fetchone()
            return dict(_json_load(row["payload_json"])) if row else None

    def find_seller_by_url(self, agent_url: str) -> dict[str, Any] | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_sellers
                WHERE agent_url = ?
                ORDER BY rowid
                LIMIT 1
                """,
                (agent_url,),
            ).fetchone()
            return dict(_json_load(row["payload_json"])) if row else None

    def owner_for_seller(self, seller_id: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT owner_id FROM commerce_sellers
                WHERE seller_id = ?
                """,
                (seller_id,),
            ).fetchone()
            return str(row["owner_id"]) if row else None

    def save_capability(
        self, seller_id: str, capability: CapabilityDescriptor
    ) -> CapabilityDescriptor:
        payload = _capability_payload(capability)
        with self._write() as connection:
            existing = connection.execute(
                """
                SELECT seller_id FROM commerce_capabilities
                WHERE capability_id = ?
                """,
                (capability.capability_id,),
            ).fetchone()
            if existing is not None and existing["seller_id"] != seller_id:
                raise ValueError("capability seller cannot be changed")
            connection.execute(
                """
                INSERT INTO commerce_capabilities(
                    capability_id, seller_id, payload_json
                ) VALUES (?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                (
                    capability.capability_id,
                    seller_id,
                    _json_dump(payload),
                ),
            )
        return capability

    def list_capabilities(self, seller_id: str) -> list[CapabilityDescriptor]:
        with self._read() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM commerce_capabilities
                WHERE seller_id = ?
                ORDER BY rowid
                """,
                (seller_id,),
            ).fetchall()
            return [
                _capability_from_payload(_json_load(row["payload_json"]))
                for row in rows
            ]

    def get_capability(
        self, capability_id: str
    ) -> CapabilityDescriptor | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_capabilities
                WHERE capability_id = ?
                """,
                (capability_id,),
            ).fetchone()
            return (
                _capability_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def save_sku(self, seller_id: str, sku: ServiceSKU) -> ServiceSKU:
        payload = _sku_payload(sku)
        with self._write() as connection:
            existing = connection.execute(
                """
                SELECT seller_id, capability_id FROM commerce_skus
                WHERE sku_id = ?
                """,
                (sku.sku_id,),
            ).fetchone()
            if existing is not None and (
                existing["seller_id"] != seller_id
                or existing["capability_id"] != sku.capability_id
            ):
                raise ValueError("SKU seller or capability cannot be changed")
            connection.execute(
                """
                INSERT INTO commerce_skus(
                    sku_id, seller_id, capability_id, payload_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(sku_id) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                (
                    sku.sku_id,
                    seller_id,
                    sku.capability_id,
                    _json_dump(payload),
                ),
            )
        return sku

    def get_sku(self, sku_id: str) -> ServiceSKU | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_skus
                WHERE sku_id = ?
                """,
                (sku_id,),
            ).fetchone()
            return (
                _sku_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def seller_for_sku(self, sku_id: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT seller_id FROM commerce_skus
                WHERE sku_id = ?
                """,
                (sku_id,),
            ).fetchone()
            return str(row["seller_id"]) if row else None

    def list_skus(self, seller_id: str) -> list[ServiceSKU]:
        with self._read() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM commerce_skus
                WHERE seller_id = ?
                ORDER BY rowid
                """,
                (seller_id,),
            ).fetchall()
            return [
                _sku_from_payload(_json_load(row["payload_json"]))
                for row in rows
            ]

    def save_policy(
        self, seller_id: str, policy: CommercialPolicy
    ) -> CommercialPolicy:
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO commerce_policies(seller_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(seller_id) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                (seller_id, _json_dump(_policy_payload(policy))),
            )
        return policy

    def get_policy(self, seller_id: str) -> CommercialPolicy | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_policies
                WHERE seller_id = ?
                """,
                (seller_id,),
            ).fetchone()
            return (
                _policy_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def save_prospect(self, prospect: ProspectRecord) -> ProspectRecord:
        need_id = prospect.need.need_id
        with self._write() as connection:
            existing = connection.execute(
                """
                SELECT owner_id FROM commerce_prospects
                WHERE need_id = ?
                """,
                (need_id,),
            ).fetchone()
            if (
                existing is not None
                and existing["owner_id"] != prospect.owner_id
            ):
                raise ValueError("prospect owner cannot be changed")
            connection.execute(
                """
                INSERT INTO commerce_prospects(
                    need_id, buyer_agent_url, owner_id, payload_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(need_id) DO UPDATE SET
                    buyer_agent_url = excluded.buyer_agent_url,
                    payload_json = excluded.payload_json
                """,
                (
                    need_id,
                    prospect.need.buyer_agent_url,
                    prospect.owner_id,
                    _json_dump(_prospect_payload(prospect)),
                ),
            )
        return prospect

    def owner_for_prospect(self, need_id: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT owner_id FROM commerce_prospects
                WHERE need_id = ?
                """,
                (need_id,),
            ).fetchone()
            return str(row["owner_id"]) if row else None

    def get_prospect(self, need_id: str) -> ProspectRecord | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_prospects
                WHERE need_id = ?
                """,
                (need_id,),
            ).fetchone()
            return (
                _prospect_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def find_prospect_by_url(
        self, buyer_agent_url: str
    ) -> ProspectRecord | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_prospects
                WHERE buyer_agent_url = ?
                ORDER BY rowid
                LIMIT 1
                """,
                (buyer_agent_url,),
            ).fetchone()
            return (
                _prospect_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def list_prospects(
        self, *, owner_id: str | None = None
    ) -> list[ProspectRecord]:
        query = "SELECT payload_json FROM commerce_prospects"
        parameters: tuple[Any, ...] = ()
        if owner_id is not None:
            query += " WHERE owner_id = ?"
            parameters = (owner_id,)
        query += " ORDER BY rowid"
        with self._read() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [
                _prospect_from_payload(_json_load(row["payload_json"]))
                for row in rows
            ]

    def save_proposal(
        self,
        proposal: Proposal,
        *,
        owner_id: str | None = None,
        contract_hash: str | None = None,
    ) -> Proposal:
        with self._write() as connection:
            existing = connection.execute(
                """
                SELECT owner_id, contract_hash, accepted, payload_json
                FROM commerce_proposals
                WHERE proposal_id = ?
                """,
                (proposal.proposal_id,),
            ).fetchone()
            current = (
                _proposal_from_payload(_json_load(existing["payload_json"]))
                if existing is not None
                else None
            )
            selected = monotonic_proposal(current, proposal)
            selected_owner = owner_id or (
                str(existing["owner_id"]) if existing is not None else None
            )
            if selected_owner is None:
                raise ValueError("proposal owner is required")
            if (
                existing is not None
                and existing["owner_id"] != selected_owner
            ):
                raise ValueError("proposal owner cannot be changed")
            selected_hash = (
                existing["contract_hash"]
                if existing is not None and selected is current
                else contract_hash
                if contract_hash is not None
                else existing["contract_hash"]
                if existing is not None
                else None
            )
            authorization = connection.execute(
                """
                SELECT proposal_contract_hash
                FROM commerce_settlement_authorizations
                WHERE proposal_id = ?
                """,
                (proposal.proposal_id,),
            ).fetchone()
            if (
                authorization is not None
                and selected_hash != authorization["proposal_contract_hash"]
            ):
                raise ValueError(
                    "accepted proposal contract hash cannot be changed"
                )
            accepted = (
                selected.state in _POST_ACCEPTANCE_STATES
                or bool(existing["accepted"])
                if existing is not None
                else selected.state in _POST_ACCEPTANCE_STATES
            )
            connection.execute(
                """
                INSERT INTO commerce_proposals(
                    proposal_id, seller_agent_url, sku_id, state, owner_id,
                    contract_hash, accepted, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    seller_agent_url = excluded.seller_agent_url,
                    sku_id = excluded.sku_id,
                    state = excluded.state,
                    contract_hash = excluded.contract_hash,
                    accepted = excluded.accepted,
                    payload_json = excluded.payload_json
                """,
                (
                    selected.proposal_id,
                    selected.seller_agent_url,
                    selected.sku_id,
                    selected.state.value,
                    selected_owner,
                    selected_hash,
                    int(accepted),
                    _json_dump(_proposal_payload(selected)),
                ),
            )
        return selected

    def accept_proposal(
        self,
        proposal: Proposal,
        authorization: SettlementAuthorization,
        *,
        owner_id: str,
        contract_hash: str,
    ) -> tuple[Proposal, SettlementAuthorization]:
        with self._write() as connection:
            existing = connection.execute(
                """
                SELECT owner_id, contract_hash, payload_json
                FROM commerce_proposals
                WHERE proposal_id = ?
                """,
                (proposal.proposal_id,),
            ).fetchone()
            if existing is None:
                raise ValueError("proposal does not exist")
            if existing["owner_id"] != owner_id:
                raise ValueError("proposal owner cannot be changed")
            current = _proposal_from_payload(
                _json_load(existing["payload_json"])
            )
            selected = monotonic_proposal(current, proposal)
            if selected.state not in _POST_ACCEPTANCE_STATES:
                raise ValueError(
                    "proposal acceptance did not reach an accepted state"
                )
            if (
                authorization.proposal_id != selected.proposal_id
                or authorization.proposal_revision != selected.revision
                or authorization.proposal_contract_hash != contract_hash
                or authorization.amount_usdc != selected.price_usdc
            ):
                raise ValueError(
                    "settlement authorization does not match accepted proposal"
                )
            existing_authorization_row = connection.execute(
                """
                SELECT payload_json
                FROM commerce_settlement_authorizations
                WHERE proposal_id = ?
                """,
                (proposal.proposal_id,),
            ).fetchone()
            existing_authorization = (
                _settlement_authorization_from_payload(
                    _json_load(existing_authorization_row["payload_json"])
                )
                if existing_authorization_row is not None
                else None
            )
            if (
                existing_authorization is not None
                and existing_authorization != authorization
            ):
                raise ValueError(
                    "settlement authorization is immutable once accepted"
                )

            connection.execute(
                """
                UPDATE commerce_proposals
                SET seller_agent_url = ?, sku_id = ?, state = ?,
                    contract_hash = ?, accepted = 1, payload_json = ?
                WHERE proposal_id = ?
                """,
                (
                    selected.seller_agent_url,
                    selected.sku_id,
                    selected.state.value,
                    contract_hash,
                    _json_dump(_proposal_payload(selected)),
                    selected.proposal_id,
                ),
            )
            if existing_authorization is None:
                try:
                    connection.execute(
                        """
                        INSERT INTO commerce_settlement_authorizations(
                            proposal_id, authorization_id,
                            proposal_revision, proposal_contract_hash,
                            expires_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            authorization.proposal_id,
                            authorization.authorization_id,
                            authorization.proposal_revision,
                            authorization.proposal_contract_hash,
                            authorization.expires_at,
                            _json_dump(
                                _settlement_authorization_payload(
                                    authorization
                                )
                            ),
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(
                        "settlement authorization conflicts with existing binding"
                    ) from exc
            return selected, existing_authorization or authorization

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_proposals
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            return (
                _proposal_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def owner_for_proposal(self, proposal_id: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT owner_id FROM commerce_proposals
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            return str(row["owner_id"]) if row else None

    def contract_hash_for_proposal(self, proposal_id: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT contract_hash FROM commerce_proposals
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            return (
                str(row["contract_hash"])
                if row is not None and row["contract_hash"] is not None
                else None
            )

    def get_settlement_authorization(
        self, proposal_id: str
    ) -> SettlementAuthorization | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM commerce_settlement_authorizations
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            return (
                _settlement_authorization_from_payload(
                    _json_load(row["payload_json"])
                )
                if row is not None
                else None
            )

    def list_proposals(
        self,
        *,
        seller_id: str | None = None,
        state: ProposalState | None = None,
        owner_id: str | None = None,
    ) -> list[Proposal]:
        conditions: list[str] = []
        parameters: list[Any] = []
        query = "SELECT p.payload_json FROM commerce_proposals AS p"
        if seller_id is not None:
            query += (
                " JOIN commerce_sellers AS s"
                " ON s.agent_url = p.seller_agent_url"
            )
            conditions.append("s.seller_id = ?")
            parameters.append(seller_id)
        if state is not None:
            conditions.append("p.state = ?")
            parameters.append(state.value)
        if owner_id is not None:
            conditions.append("p.owner_id = ?")
            parameters.append(owner_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY p.rowid"
        with self._read() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
            return [
                _proposal_from_payload(_json_load(row["payload_json"]))
                for row in rows
            ]

    def mark_accepted(self, proposal_id: str) -> None:
        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE commerce_proposals
                SET accepted = 1
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("proposal does not exist")

    def record_negotiation(self, delta: Decimal) -> None:
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO commerce_negotiation_events(delta_usdc)
                VALUES (?)
                """,
                (format(delta, "f"),),
            )

    def _increment_counter(self, name: str) -> None:
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO commerce_counters(name, value)
                VALUES (?, 1)
                ON CONFLICT(name) DO UPDATE SET
                    value = value + 1
                """,
                (name,),
            )

    def note_policy_denial(self) -> None:
        self._increment_counter("policy_denials")

    def note_duplicate_payment(self) -> None:
        self._increment_counter("duplicate_payment_attempts")

    def get_payment(self, payment_id: str) -> PaymentReceipt | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_payments
                WHERE payment_id = ?
                """,
                (payment_id,),
            ).fetchone()
            return (
                _payment_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def owner_for_payment(self, payment_id: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT p.owner_id
                FROM commerce_payments AS payment
                JOIN commerce_proposals AS p
                  ON p.proposal_id = payment.proposal_id
                WHERE payment.payment_id = ?
                """,
                (payment_id,),
            ).fetchone()
            return str(row["owner_id"]) if row else None

    def payment_for_proposal(
        self, proposal_id: str
    ) -> PaymentReceipt | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_payments
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            return (
                _payment_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def payment_for_idempotency(
        self, key: str
    ) -> PaymentReceipt | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_payments
                WHERE idempotency_key = ?
                """,
                (key,),
            ).fetchone()
            return (
                _payment_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def save_payment(
        self, receipt: PaymentReceipt, *, mocked: bool
    ) -> PaymentReceipt:
        mapping = self._payment_mapping(receipt)
        with self._write() as connection:
            rows = connection.execute(
                """
                SELECT * FROM commerce_payments
                WHERE payment_id = ? OR proposal_id = ? OR idempotency_key = ?
                   OR (
                       transaction_hash_key IS NOT NULL
                       AND transaction_hash_key = ?
                   )
                """,
                (
                    mapping.payment_id,
                    mapping.proposal_id,
                    mapping.idempotency_key,
                    mapping.transaction_hash_key,
                ),
            ).fetchall()
            if rows:
                exact = None
                for row in rows:
                    existing = _PaymentMapping(
                        payment_id=row["payment_id"],
                        proposal_id=row["proposal_id"],
                        idempotency_key=row["idempotency_key"],
                        transaction_hash_key=row["transaction_hash_key"],
                    )
                    if existing == mapping:
                        exact = row
                    elif row["proposal_id"] == mapping.proposal_id:
                        raise ValueError(
                            "proposal already has a different payment"
                        )
                    elif row["idempotency_key"] == mapping.idempotency_key:
                        raise ValueError(
                            "idempotency key already has a different payment"
                        )
                    elif (
                        mapping.transaction_hash_key is not None
                        and row["transaction_hash_key"]
                        == mapping.transaction_hash_key
                    ):
                        raise ValueError(
                            "transaction hash already has a different payment"
                        )
                    else:
                        raise ValueError("payment ID already has different data")
                if exact is not None:
                    existing_receipt = _payment_from_payload(
                        _json_load(exact["payload_json"])
                    )
                    if (
                        existing_receipt != receipt
                        or bool(exact["mocked"]) != bool(mocked)
                    ):
                        raise ValueError(
                            "existing payment evidence cannot be rewritten"
                        )
                    return existing_receipt

            try:
                self._insert_payment(
                    connection,
                    receipt,
                    mocked=mocked,
                )
                proposal = connection.execute(
                    """
                    SELECT state FROM commerce_proposals
                    WHERE proposal_id = ?
                    """,
                    (receipt.proposal_id,),
                ).fetchone()
                if proposal is None:
                    raise ValueError("payment proposal does not exist")
                authorization_row = connection.execute(
                    """
                    SELECT payload_json
                    FROM commerce_settlement_authorizations
                    WHERE proposal_id = ?
                    """,
                    (receipt.proposal_id,),
                ).fetchone()
                authorization = (
                    _settlement_authorization_from_payload(
                        _json_load(authorization_row["payload_json"])
                    )
                    if authorization_row is not None
                    else None
                )
                if authorization is None or not (
                    payment_matches_settlement_authorization(
                        receipt, authorization
                    )
                ):
                    raise ValueError(
                        "payment does not match immutable settlement authorization"
                    )
                current_state = ProposalState(proposal["state"])
                if current_state is ProposalState.ACCEPTED:
                    self._set_proposal_state(
                        connection,
                        receipt.proposal_id,
                        ProposalState.PAID,
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError("duplicate or invalid payment mapping") from exc
        return receipt

    def is_mocked_payment(self, payment_id: str) -> bool:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT mocked FROM commerce_payments
                WHERE payment_id = ?
                """,
                (payment_id,),
            ).fetchone()
            return bool(row["mocked"]) if row else False

    def recent_paid_count(self, seller_id: str, *, hours: int = 1) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._read() as connection:
            seller = connection.execute(
                """
                SELECT agent_url FROM commerce_sellers
                WHERE seller_id = ?
                """,
                (seller_id,),
            ).fetchone()
            if seller is None:
                return 0
            rows = connection.execute(
                """
                SELECT payment.payload_json
                FROM commerce_payments AS payment
                JOIN commerce_proposals AS proposal
                  ON proposal.proposal_id = payment.proposal_id
                WHERE proposal.seller_agent_url = ?
                """,
                (seller["agent_url"],),
            ).fetchall()
            count = 0
            for row in rows:
                payment = _payment_from_payload(
                    _json_load(row["payload_json"])
                )
                if not payment.confirmed_at:
                    count += 1
                    continue
                try:
                    timestamp = datetime.fromisoformat(
                        payment.confirmed_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    count += 1
                    continue
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if timestamp >= cutoff:
                    count += 1
            return count

    def get_fulfillment(
        self, fulfillment_id: str
    ) -> FulfillmentReceipt | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_fulfillments
                WHERE fulfillment_id = ?
                """,
                (fulfillment_id,),
            ).fetchone()
            return (
                _fulfillment_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def owner_for_fulfillment(self, fulfillment_id: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT proposal.owner_id
                FROM commerce_fulfillments AS fulfillment
                JOIN commerce_proposals AS proposal
                  ON proposal.proposal_id = fulfillment.proposal_id
                WHERE fulfillment.fulfillment_id = ?
                """,
                (fulfillment_id,),
            ).fetchone()
            return str(row["owner_id"]) if row else None

    def fulfillment_for_proposal(
        self, proposal_id: str
    ) -> FulfillmentReceipt | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM commerce_fulfillments
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            return (
                _fulfillment_from_payload(_json_load(row["payload_json"]))
                if row
                else None
            )

    def save_fulfillment(
        self, receipt: FulfillmentReceipt
    ) -> FulfillmentReceipt:
        with self._write() as connection:
            rows = connection.execute(
                """
                SELECT * FROM commerce_fulfillments
                WHERE fulfillment_id = ? OR proposal_id = ? OR payment_id = ?
                """,
                (
                    receipt.fulfillment_id,
                    receipt.proposal_id,
                    receipt.payment_id,
                ),
            ).fetchall()
            if rows:
                for row in rows:
                    existing = _fulfillment_from_payload(
                        _json_load(row["payload_json"])
                    )
                    if existing == receipt:
                        return existing
                    if row["proposal_id"] == receipt.proposal_id:
                        raise ValueError(
                            "proposal already has a different fulfillment"
                        )
                    if row["payment_id"] == receipt.payment_id:
                        raise ValueError(
                            "payment already has a different fulfillment"
                        )
                raise ValueError("fulfillment ID already has different data")

            payment = connection.execute(
                """
                SELECT proposal_id FROM commerce_payments
                WHERE payment_id = ?
                """,
                (receipt.payment_id,),
            ).fetchone()
            if payment is None or payment["proposal_id"] != receipt.proposal_id:
                raise ValueError(
                    "fulfillment payment is missing or belongs to another proposal"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO commerce_fulfillments(
                        fulfillment_id, proposal_id, payment_id,
                        accepted, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        receipt.fulfillment_id,
                        receipt.proposal_id,
                        receipt.payment_id,
                        int(receipt.accepted),
                        _json_dump(_fulfillment_payload(receipt)),
                    ),
                )
                self._set_proposal_state(
                    connection,
                    receipt.proposal_id,
                    (
                        ProposalState.DELIVERED
                        if receipt.accepted
                        else ProposalState.FAILED
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "duplicate or invalid fulfillment mapping"
                ) from exc
        return receipt

    def save_receipt_publication(
        self, publication: ReceiptPublication
    ) -> ReceiptPublication:
        with self._write() as connection:
            proposal = connection.execute(
                """
                SELECT owner_id FROM commerce_proposals
                WHERE proposal_id = ?
                """,
                (publication.proposal_id,),
            ).fetchone()
            if (
                proposal is None
                or proposal["owner_id"] != publication.owner_id
            ):
                raise ValueError(
                    "receipt publication owner does not match proposal"
                )
            existing = connection.execute(
                """
                SELECT * FROM commerce_receipt_publications
                WHERE proposal_id = ? OR receipt_id = ?
                """,
                (publication.proposal_id, publication.receipt_id),
            ).fetchall()
            if existing:
                for row in existing:
                    current = _publication_from_row(row)
                    if (
                        current.proposal_id == publication.proposal_id
                        and current.receipt_id == publication.receipt_id
                        and current.owner_id == publication.owner_id
                        and current.consent_reference
                        == publication.consent_reference
                        and current.fields == publication.fields
                    ):
                        return current
                raise ValueError(
                    "receipt is already published under a different authorization"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO commerce_receipt_publications(
                        receipt_id, proposal_id, owner_id, approved_by,
                        consent_reference, fields_json, published_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        publication.receipt_id,
                        publication.proposal_id,
                        publication.owner_id,
                        publication.approved_by,
                        publication.consent_reference,
                        _json_dump(list(publication.fields)),
                        publication.published_at,
                        publication.version,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "receipt publication mapping is not unique"
                ) from exc
        return publication

    def get_receipt_publication(
        self, receipt_id: str
    ) -> ReceiptPublication | None:
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT * FROM commerce_receipt_publications
                WHERE receipt_id = ? OR proposal_id = ?
                ORDER BY CASE WHEN receipt_id = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (receipt_id, receipt_id, receipt_id),
            ).fetchone()
            return _publication_from_row(row) if row else None

    @staticmethod
    def _counter(
        connection: sqlite3.Connection, name: str
    ) -> int:
        row = connection.execute(
            """
            SELECT value FROM commerce_counters
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
        return int(row["value"]) if row else 0

    def metrics(self, *, owner_id: str | None = None) -> dict[str, Any]:
        with self._read() as connection:
            proposal_query = (
                "SELECT proposal_id, payload_json, accepted "
                "FROM commerce_proposals"
            )
            parameters: tuple[Any, ...] = ()
            if owner_id is not None:
                proposal_query += " WHERE owner_id = ?"
                parameters = (owner_id,)
            proposal_rows = connection.execute(
                proposal_query, parameters
            ).fetchall()
            proposal_ids = {row["proposal_id"] for row in proposal_rows}
            proposals = [
                _proposal_from_payload(_json_load(row["payload_json"]))
                for row in proposal_rows
            ]
            accepted_count = sum(
                1 for row in proposal_rows if bool(row["accepted"])
            )

            payment_rows = connection.execute(
                """
                SELECT payload_json, mocked FROM commerce_payments
                ORDER BY rowid
                """
            ).fetchall()
            payments = [
                (
                    _payment_from_payload(_json_load(row["payload_json"])),
                    bool(row["mocked"]),
                )
                for row in payment_rows
                if _json_load(row["payload_json"])["proposal_id"] in proposal_ids
            ]
            confirmed = [
                (payment, mocked)
                for payment, mocked in payments
                if payment.state is PaymentState.CONFIRMED
            ]
            live = [
                payment
                for payment, mocked in confirmed
                if not mocked and "TEST" not in payment.chain.upper()
            ]
            mocked_payments = [
                payment
                for payment, mocked in confirmed
                if mocked or "TEST" in payment.chain.upper()
            ]

            fulfillment_rows = connection.execute(
                """
                SELECT payload_json FROM commerce_fulfillments
                ORDER BY rowid
                """
            ).fetchall()
            fulfillments = [
                _fulfillment_from_payload(_json_load(row["payload_json"]))
                for row in fulfillment_rows
            ]
            fulfillment_by_proposal = {
                item.proposal_id: item for item in fulfillments
            }
            successful = [
                item
                for item in fulfillments
                if item.accepted and item.proposal_id in proposal_ids
            ]

            seller_query = (
                "SELECT seller_id FROM commerce_sellers"
                if owner_id is None
                else "SELECT seller_id FROM commerce_sellers WHERE owner_id = ?"
            )
            seller_parameters = () if owner_id is None else (owner_id,)
            seller_ids = [
                row["seller_id"]
                for row in connection.execute(
                    seller_query, seller_parameters
                ).fetchall()
            ]
            activated = 0
            for seller_id in seller_ids:
                has_policy = connection.execute(
                    """
                    SELECT 1 FROM commerce_policies
                    WHERE seller_id = ?
                    """,
                    (seller_id,),
                ).fetchone()
                has_sku = connection.execute(
                    """
                    SELECT 1 FROM commerce_skus
                    WHERE seller_id = ?
                    LIMIT 1
                    """,
                    (seller_id,),
                ).fetchone()
                if has_policy is not None and has_sku is not None:
                    activated += 1

            deltas = [
                Decimal(row["delta_usdc"])
                for row in connection.execute(
                    """
                    SELECT delta_usdc FROM commerce_negotiation_events
                    ORDER BY event_id
                    """
                ).fetchall()
            ]
            negotiated_total = sum(
                (abs(delta) for delta in deltas), Decimal("0")
            )

            delivery_seconds: list[float] = []
            for payment, _mocked in confirmed:
                fulfillment = fulfillment_by_proposal.get(payment.proposal_id)
                if (
                    fulfillment is None
                    or not fulfillment.accepted
                    or not payment.confirmed_at
                    or not fulfillment.delivered_at
                ):
                    continue
                try:
                    confirmed_at = datetime.fromisoformat(
                        payment.confirmed_at.replace("Z", "+00:00")
                    )
                    delivered_at = datetime.fromisoformat(
                        fulfillment.delivered_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if confirmed_at.tzinfo is None:
                    confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
                if delivered_at.tzinfo is None:
                    delivered_at = delivered_at.replace(tzinfo=timezone.utc)
                elapsed = (delivered_at - confirmed_at).total_seconds()
                if elapsed >= 0:
                    delivery_seconds.append(elapsed)

            acceptance_rate = (
                Decimal(accepted_count) / Decimal(len(proposals))
                if proposals
                else Decimal("0")
            )
            return {
                "registeredSellerAgents": len(seller_ids),
                "activatedSellerAgents": activated,
                "proposalsSent": len(proposals),
                "proposalAcceptanceRate": format(acceptance_rate, "f"),
                "negotiatedPriceChangeUsdc": usdc_text(
                    abs(negotiated_total)
                ),
                "paidTasks": None,
                "paidTasksStatus": (
                    "requires_external_customer_classification"
                ),
                "confirmedLivePayments": len(live),
                "mockedPaymentCount": len(mocked_payments),
                "usdcRevenue": None,
                "liveSettlementVolumeUsdc": usdc_text(
                    sum(
                        (payment.amount_usdc for payment in live),
                        Decimal("0"),
                    )
                ),
                "mockedPaymentVolumeUsdc": usdc_text(
                    sum(
                        (
                            payment.amount_usdc
                            for payment in mocked_payments
                        ),
                        Decimal("0"),
                    )
                ),
                "successfulFulfillment": len(successful),
                "medianDeliverySeconds": (
                    float(median(delivery_seconds))
                    if delivery_seconds
                    else None
                ),
                "repeatPurchaseRate": None,
                "repeatPurchaseRateStatus": (
                    "requires_external_customer_classification"
                ),
                "paymentFailures": sum(
                    1
                    for payment, _mocked in payments
                    if payment.state
                    in (
                        PaymentState.FAILED_RETRYABLE,
                        PaymentState.FAILED_TERMINAL,
                    )
                ),
                "policyDenials": self._counter(
                    connection, "policy_denials"
                ),
                "duplicatePaymentCount": self._counter(
                    connection, "duplicate_payment_attempts"
                ),
                "grossMarginUsdc": None,
                "grossMarginStatus": (
                    "requires_measured_variable_costs"
                ),
                "revenueClassification": (
                    "unmeasured_external_customer_status"
                ),
            }


SQLiteCommerceRepository = SQLiteRepository

__all__ = ["SQLiteCommerceRepository", "SQLiteRepository"]
