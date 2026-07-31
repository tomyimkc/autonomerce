"""Dependency-free payment models and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from autonomerce.contracts import (
    CommercialPolicy,
    ContractError,
    Proposal,
    ProposalState,
    stable_id,
    usdc,
    usdc_text,
)

from .errors import PaymentValidationError


_EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_TX_HASH = re.compile(r"^0x[a-fA-F0-9]{64}$")
_SAFE_KEY = re.compile(r"^[\x21-\x7e]{1,128}$")
_SAFE_CHAIN = re.compile(r"^[A-Z0-9][A-Z0-9:-]{1,63}$")
_SHA256_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
_ZERO_EVM_ADDRESS = "0x" + ("0" * 40)
_ZERO_TX_HASH = "0x" + ("0" * 64)


_CHAIN_ALIASES = {
    "BASE": "BASE",
    "BASE-MAINNET": "BASE",
    "BASE-SEPOLIA": "BASE-SEPOLIA",
    "ARC-TESTNET": "ARC-TESTNET",
    "EIP155:8453": "BASE",
    "EIP155:84532": "BASE-SEPOLIA",
}


# x402 requirements identify assets by contract address. These values are used only
# for deterministic token classification; policies can replace/extend them with an
# explicit allowed_assets_by_chain allowlist.
KNOWN_USDC_ASSETS: Mapping[str, tuple[str, ...]] = {
    "BASE": ("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",),
    "BASE-SEPOLIA": ("0x036cbd53842c5426634e7929541ec2318f3dcf7e",),
    "ARC-TESTNET": ("0x3600000000000000000000000000000000000000",),
}


class PaymentMode(str, Enum):
    """Execution environment.

    OFFLINE never invokes Circle. TESTNET invokes only recognized test networks.
    MAINNET may move real funds and requires explicit policy and executor opt-in.
    """

    OFFLINE = "offline"
    TESTNET = "testnet"
    MAINNET = "mainnet"

    @classmethod
    def parse(cls, value: "PaymentMode | str") -> "PaymentMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise PaymentValidationError("invalid payment mode") from exc

    @property
    def is_live(self) -> bool:
        return self is not PaymentMode.OFFLINE


def canonical_chain(value: str) -> str:
    chain = str(value).strip().upper().replace("_", "-")
    chain = _CHAIN_ALIASES.get(chain, chain)
    if not _SAFE_CHAIN.fullmatch(chain):
        raise PaymentValidationError("invalid blockchain identifier")
    return chain


def is_testnet_chain(chain: str) -> bool:
    normalized = canonical_chain(chain)
    return normalized.endswith("-TESTNET") or normalized.endswith("-SEPOLIA")


def is_mainnet_chain(chain: str) -> bool:
    return not is_testnet_chain(chain)


def normalize_wallet_address(value: str, chain: str) -> str:
    """Validate and normalize a Circle-supported EVM wallet address.

    Autonomerce currently supports the Base/Arc EVM lane only. Unknown address
    families are rejected rather than guessed.
    """

    normalized_chain = canonical_chain(chain)
    if normalized_chain not in {"BASE", "BASE-SEPOLIA", "ARC-TESTNET"}:
        raise PaymentValidationError(
            f"unsupported wallet address family for chain {normalized_chain}"
        )
    wallet = str(value).strip()
    if not _EVM_ADDRESS.fullmatch(wallet) or wallet.lower() == _ZERO_EVM_ADDRESS:
        raise PaymentValidationError("invalid or zero EVM wallet address")
    return wallet


def normalize_transaction_hash(value: str) -> str:
    transaction_hash = str(value).strip()
    if (
        not _TX_HASH.fullmatch(transaction_hash)
        or transaction_hash.lower() == _ZERO_TX_HASH
    ):
        raise PaymentValidationError("invalid or zero transaction hash")
    return transaction_hash


def normalize_idempotency_key(value: str) -> str:
    key = str(value).strip()
    if not _SAFE_KEY.fullmatch(key):
        raise PaymentValidationError(
            "idempotency key must be 1-128 visible ASCII characters without spaces"
        )
    return key


def normalize_token(value: str) -> str:
    token = str(value).strip().upper()
    if not token or len(token) > 32 or not token.replace("-", "").isalnum():
        raise PaymentValidationError("invalid payment token")
    return token


def normalize_asset_contract(
    value: str | None,
    chain: str,
    *,
    token: str = "USDC",
) -> str | None:
    if value is None or not str(value).strip():
        return None
    asset = str(value).strip()
    normalized_token = normalize_token(token)
    if asset.upper() == normalized_token:
        return normalized_token
    return normalize_wallet_address(asset, chain).lower()


def _normalize_wallets(values: tuple[str, ...], chains: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        return ()
    # All currently supported chains share EVM address syntax.
    validation_chain = chains[0] if chains else "BASE"
    return tuple(
        dict.fromkeys(
            normalize_wallet_address(value, validation_chain).lower() for value in values
        )
    )


def _normalize_hosts(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        host = str(value).strip().lower().rstrip(".")
        if (
            not host
            or "/" in host
            or ":" in host
            or any(character.isspace() for character in host)
        ):
            raise PaymentValidationError("invalid resource host in payment policy")
        normalized.append(host)
    return tuple(dict.fromkeys(normalized))


@dataclass(frozen=True)
class PaymentIntent:
    """A policy-bound request to pay exactly one accepted proposal."""

    proposal_id: str
    idempotency_key: str
    amount_usdc: Decimal
    chain: str
    token: str
    payer_wallet: str
    payee_wallet: str
    proposal_state: ProposalState = ProposalState.ACCEPTED
    expected_amount_usdc: Decimal | None = None
    asset: str | None = None
    scheme: str = "exact"
    x402_requirement_id: str | None = None
    x402_requirement_fingerprint: str | None = None
    resource_url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.proposal_id).strip():
            raise PaymentValidationError("proposal_id is required")
        amount = usdc(self.amount_usdc)
        if amount <= 0:
            raise PaymentValidationError("payment amount must be greater than zero")
        expected = (
            amount
            if self.expected_amount_usdc is None
            else usdc(self.expected_amount_usdc)
        )
        chain = canonical_chain(self.chain)
        token = normalize_token(self.token)
        payer = normalize_wallet_address(self.payer_wallet, chain)
        payee = normalize_wallet_address(self.payee_wallet, chain)
        scheme = str(self.scheme).strip().lower()
        if not scheme or len(scheme) > 32 or not scheme.replace("-", "").isalnum():
            raise PaymentValidationError("invalid payment scheme")
        requirement_id = (
            normalize_idempotency_key(self.x402_requirement_id)
            if self.x402_requirement_id is not None
            else None
        )
        requirement_fingerprint = (
            str(self.x402_requirement_fingerprint).strip().lower()
            if self.x402_requirement_fingerprint is not None
            else None
        )
        if (
            requirement_fingerprint is not None
            and not _SHA256_FINGERPRINT.fullmatch(requirement_fingerprint)
        ):
            raise PaymentValidationError(
                "invalid x402 requirement fingerprint"
            )
        resource_url = str(self.resource_url).strip() if self.resource_url else None
        if resource_url:
            parsed = urlsplit(resource_url)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                raise PaymentValidationError("invalid x402 resource URL")
            if parsed.username or parsed.password:
                raise PaymentValidationError("resource URL must not contain credentials")
        try:
            proposal_state = ProposalState(self.proposal_state)
        except ValueError as exc:
            raise PaymentValidationError("invalid proposal state") from exc

        object.__setattr__(self, "idempotency_key", normalize_idempotency_key(self.idempotency_key))
        object.__setattr__(self, "amount_usdc", amount)
        object.__setattr__(self, "expected_amount_usdc", expected)
        object.__setattr__(self, "chain", chain)
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "payer_wallet", payer)
        object.__setattr__(self, "payee_wallet", payee)
        object.__setattr__(self, "proposal_state", proposal_state)
        object.__setattr__(self, "scheme", scheme)
        object.__setattr__(self, "x402_requirement_id", requirement_id)
        object.__setattr__(
            self,
            "x402_requirement_fingerprint",
            requirement_fingerprint,
        )
        object.__setattr__(self, "resource_url", resource_url)
        normalized_asset = normalize_asset_contract(self.asset, chain, token=token)
        if normalized_asset is None and token == "USDC":
            known_assets = KNOWN_USDC_ASSETS.get(chain, ())
            if known_assets:
                normalized_asset = known_assets[0]
        object.__setattr__(self, "asset", normalized_asset)

    @classmethod
    def from_proposal(
        cls,
        proposal: Proposal,
        *,
        idempotency_key: str,
        chain: str,
        payer_wallet: str,
        payee_wallet: str,
        token: str = "USDC",
        **kwargs: Any,
    ) -> "PaymentIntent":
        return cls(
            proposal_id=proposal.proposal_id,
            idempotency_key=idempotency_key,
            amount_usdc=proposal.price_usdc,
            expected_amount_usdc=proposal.price_usdc,
            proposal_state=proposal.state,
            chain=chain,
            token=token,
            payer_wallet=payer_wallet,
            payee_wallet=payee_wallet,
            **kwargs,
        )

    @property
    def fingerprint(self) -> str:
        security_fields = {
            "proposalId": self.proposal_id,
            "amountUsdc": usdc_text(self.amount_usdc),
            "expectedAmountUsdc": usdc_text(self.expected_amount_usdc),
            "proposalState": self.proposal_state.value,
            "chain": self.chain,
            "token": self.token,
            "asset": self.asset.lower() if self.asset else None,
            "payerWallet": self.payer_wallet.lower(),
            "payeeWallet": self.payee_wallet.lower(),
            "scheme": self.scheme,
            "x402RequirementId": self.x402_requirement_id,
            "x402RequirementFingerprint": self.x402_requirement_fingerprint,
            "resourceUrl": self.resource_url,
        }
        encoded = json.dumps(
            security_fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def payment_id(self) -> str:
        return stable_id("payment", self.idempotency_key, self.fingerprint)


@dataclass(frozen=True)
class PaymentPolicy:
    """Owner-approved deterministic financial policy."""

    policy_id: str
    mode: PaymentMode
    maximum_per_payment_usdc: Decimal
    maximum_total_usdc: Decimal
    allowed_chains: tuple[str, ...]
    allowed_token: str = "USDC"
    allowed_payer_wallets: tuple[str, ...] = ()
    allowed_payee_wallets: tuple[str, ...] = ()
    maximum_payment_count: int = 100
    allowed_schemes: tuple[str, ...] = ("exact",)
    allowed_assets_by_chain: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    allowed_resource_hosts: tuple[str, ...] = ()
    blocked_resource_hosts: tuple[str, ...] = ()
    require_payer_allowlist: bool = True
    require_payee_allowlist: bool = True
    require_x402_requirement_id: bool = False
    allow_self_payment: bool = False
    mainnet_enabled: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        if not str(self.policy_id).strip():
            raise PaymentValidationError("payment policy_id is required")
        mode = PaymentMode.parse(self.mode)
        per_payment = usdc(self.maximum_per_payment_usdc)
        total = usdc(self.maximum_total_usdc)
        if per_payment <= 0 or total <= 0:
            raise PaymentValidationError("payment policy limits must be greater than zero")
        if self.maximum_payment_count < 1:
            raise PaymentValidationError("maximum_payment_count must be positive")
        chains = tuple(dict.fromkeys(canonical_chain(chain) for chain in self.allowed_chains))
        if not chains:
            raise PaymentValidationError("at least one allowed chain is required")
        token = normalize_token(self.allowed_token)
        schemes = tuple(
            dict.fromkeys(str(scheme).strip().lower() for scheme in self.allowed_schemes)
        )
        if not schemes or any(not scheme for scheme in schemes):
            raise PaymentValidationError("at least one allowed payment scheme is required")
        assets: dict[str, tuple[str, ...]] = {}
        for raw_chain, raw_assets in self.allowed_assets_by_chain.items():
            chain = canonical_chain(raw_chain)
            if chain not in chains:
                raise PaymentValidationError(
                    "asset allowlist contains a chain not allowed by policy"
                )
            values = tuple(
                dict.fromkeys(
                    normalize_asset_contract(asset, chain, token=token)
                    for asset in raw_assets
                    if str(asset).strip()
                )
            )
            if not values:
                raise PaymentValidationError("asset allowlist entries must not be empty")
            assets[chain] = values

        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "maximum_per_payment_usdc", per_payment)
        object.__setattr__(self, "maximum_total_usdc", total)
        object.__setattr__(self, "allowed_chains", chains)
        object.__setattr__(self, "allowed_token", token)
        object.__setattr__(
            self, "allowed_payer_wallets", _normalize_wallets(self.allowed_payer_wallets, chains)
        )
        object.__setattr__(
            self, "allowed_payee_wallets", _normalize_wallets(self.allowed_payee_wallets, chains)
        )
        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(self, "allowed_assets_by_chain", assets)
        object.__setattr__(
            self, "allowed_resource_hosts", _normalize_hosts(self.allowed_resource_hosts)
        )
        object.__setattr__(
            self, "blocked_resource_hosts", _normalize_hosts(self.blocked_resource_hosts)
        )

    @classmethod
    def from_commercial_policy(
        cls,
        commercial_policy: CommercialPolicy,
        *,
        mode: PaymentMode | str,
        payer_wallets: tuple[str, ...],
        payee_wallets: tuple[str, ...],
        maximum_total_usdc: Decimal | str | int | None = None,
        **kwargs: Any,
    ) -> "PaymentPolicy":
        total = (
            commercial_policy.maximum_price_usdc
            if maximum_total_usdc is None
            else usdc(maximum_total_usdc)
        )
        return cls(
            policy_id=commercial_policy.policy_id,
            mode=PaymentMode.parse(mode),
            maximum_per_payment_usdc=commercial_policy.maximum_price_usdc,
            maximum_total_usdc=total,
            allowed_chains=commercial_policy.allowed_chains,
            allowed_token=commercial_policy.allowed_token,
            allowed_payer_wallets=payer_wallets,
            allowed_payee_wallets=payee_wallets,
            **kwargs,
        )


@dataclass(frozen=True)
class SpendingSnapshot:
    committed_usdc: Decimal = Decimal("0")
    committed_payment_count: int = 0

    def __post_init__(self) -> None:
        amount = usdc(self.committed_usdc)
        if self.committed_payment_count < 0:
            raise PaymentValidationError("committed payment count must be non-negative")
        object.__setattr__(self, "committed_usdc", amount)


@dataclass(frozen=True)
class PaymentPolicyDecision:
    authorized: bool
    reason_code: str
    explanation: str
    policy_id: str
    payment_id: str


@dataclass(frozen=True)
class ExecutionResult:
    """Executor evidence prior to independent receipt verification."""

    state: str
    amount_usdc: Decimal
    chain: str
    payer_wallet: str
    payee_wallet: str
    transaction_hash: str | None
    confirmed_at: str | None
    explorer_url: str | None = None
    simulated: bool = False
    provider_reference: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)
    token: str = "USDC"
    asset: str | None = None

    def __post_init__(self) -> None:
        state = str(self.state).strip().upper()
        if state not in {"CONFIRMED", "FAILED"}:
            raise PaymentValidationError("unsupported executor result state")
        chain = canonical_chain(self.chain)
        amount = usdc(self.amount_usdc)
        payer = normalize_wallet_address(self.payer_wallet, chain)
        payee = normalize_wallet_address(self.payee_wallet, chain)
        token = normalize_token(self.token)
        asset = normalize_asset_contract(self.asset, chain, token=token)
        if asset is None and token == "USDC":
            known_assets = KNOWN_USDC_ASSETS.get(chain, ())
            if known_assets:
                asset = known_assets[0]
        transaction_hash = (
            normalize_transaction_hash(self.transaction_hash)
            if self.transaction_hash is not None
            else None
        )
        if state == "CONFIRMED" and transaction_hash is None:
            raise PaymentValidationError("confirmed execution requires transaction hash")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "chain", chain)
        object.__setattr__(self, "amount_usdc", amount)
        object.__setattr__(self, "payer_wallet", payer)
        object.__setattr__(self, "payee_wallet", payee)
        object.__setattr__(self, "transaction_hash", transaction_hash)
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "asset", asset)


@dataclass(frozen=True)
class ReceiptVerification:
    verified: bool
    reason_code: str
    explanation: str
    hook_results: tuple[str, ...] = ()


def resource_host(resource_url: str | None) -> str | None:
    if not resource_url:
        return None
    try:
        return urlsplit(resource_url).hostname.lower().rstrip(".")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        return None


def contract_error_to_validation(exc: ContractError) -> PaymentValidationError:
    return PaymentValidationError(str(exc))
