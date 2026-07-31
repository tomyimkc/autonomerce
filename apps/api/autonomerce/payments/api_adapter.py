"""Optional adapter consumed by the parallel API-composition lane.

The zero-argument factory defaults to credential-free offline execution. Documented
Circle environment variables are mapped to the payment policy, while live modes
fail closed unless their durable store, exact network, wallet allowlists, and caps
are complete. Mainnet additionally requires both executor opt-ins.
"""

from __future__ import annotations

from decimal import Decimal
from importlib import import_module
import inspect
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from autonomerce.api.adapters import PaymentExecution
from autonomerce.contracts import Proposal, usdc

from .errors import PaymentValidationError
from .executors import (
    DEFAULT_CIRCLE_BINARY,
    MAINNET_CONFIRMATION,
    CircleCLIExecutor,
    CircleExecutor,
    OfflineCircleExecutor,
)
from .models import (
    PaymentIntent,
    PaymentMode,
    PaymentPolicy,
    canonical_chain,
    is_testnet_chain,
)
from .service import PaymentProcessor
from .store import (
    InMemoryPaymentStore,
    PaymentStore,
    SQLitePaymentStore,
    StoreDurability,
)
from .verification import (
    ReceiptHook,
    has_independent_transaction_lookup,
    transaction_lookup_hook,
)


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _configured_value(
    env: Mapping[str, str],
    *names: str,
    default: str | None = None,
) -> str | None:
    configured = [
        (name, str(env[name]).strip())
        for name in names
        if env.get(name) is not None and str(env[name]).strip()
    ]
    if not configured:
        return default
    values = tuple(dict.fromkeys(value for _, value in configured))
    if len(values) > 1:
        joined = ", ".join(name for name, _ in configured)
        raise PaymentValidationError(
            f"conflicting payment configuration aliases: {joined}"
        )
    return values[0]


def _configured_usdc(
    env: Mapping[str, str],
    *names: str,
    default: str,
) -> Decimal:
    configured = [
        (name, usdc(str(env[name]).strip()))
        for name in names
        if env.get(name) is not None and str(env[name]).strip()
    ]
    if not configured:
        return usdc(default)
    values = tuple(dict.fromkeys(value for _, value in configured))
    if len(values) > 1:
        joined = ", ".join(name for name, _ in configured)
        raise PaymentValidationError(
            f"conflicting payment limit aliases: {joined}"
        )
    return values[0]


def _supported_network(value: str | None) -> str | None:
    if value is None:
        return None
    network = canonical_chain(value)
    if network not in {"ARC-TESTNET", "BASE-SEPOLIA", "BASE"}:
        raise PaymentValidationError(
            "AUTONOMERCE_CIRCLE_NETWORK is not a supported Circle chain"
        )
    return network


def _load_transaction_lookup(
    env: Mapping[str, str],
) -> Callable[[str], Mapping[str, Any] | None]:
    factory_path = str(
        env.get("AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY", "")
    ).strip()
    if not factory_path or ":" not in factory_path:
        raise PaymentValidationError(
            "live modes require AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY"
        )
    module_name, attribute = factory_path.rsplit(":", 1)
    try:
        factory = getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise PaymentValidationError(
            "transaction lookup factory could not be imported"
        ) from exc
    if not callable(factory):
        raise PaymentValidationError("transaction lookup factory is not callable")
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        parameters = {}
    try:
        lookup = factory(environment=env) if "environment" in parameters else factory()
    except Exception as exc:
        raise PaymentValidationError(
            "transaction lookup factory failed"
        ) from exc
    if not callable(lookup):
        raise PaymentValidationError(
            "transaction lookup factory must return a callable"
        )
    return lookup


def _environment_mode(
    env: Mapping[str, str],
    *,
    network: str | None,
) -> PaymentMode:
    runtime_value = _configured_value(env, "AUTONOMERCE_MODE")
    payment_value = _configured_value(env, "AUTONOMERCE_PAYMENT_MODE")

    def parse_payment(
        value: str | None,
        variable: str,
    ) -> PaymentMode | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized == "live":
            raise PaymentValidationError(
                f"{variable}=live must be paired with "
                "AUTONOMERCE_PAYMENT_MODE=testnet or mainnet"
            )
        return PaymentMode.parse(normalized)

    payment_mode = parse_payment(
        payment_value,
        "AUTONOMERCE_PAYMENT_MODE",
    )
    runtime_normalized = (
        runtime_value.strip().lower() if runtime_value is not None else None
    )
    if runtime_normalized == "live":
        if payment_mode is not None:
            return payment_mode
        if network is not None:
            return (
                PaymentMode.TESTNET
                if is_testnet_chain(network)
                else PaymentMode.MAINNET
            )
        raise PaymentValidationError(
            "AUTONOMERCE_MODE=live requires "
            "AUTONOMERCE_PAYMENT_MODE=testnet or mainnet"
        )

    runtime_mode = parse_payment(runtime_value, "AUTONOMERCE_MODE")
    if (
        runtime_mode is not None
        and payment_mode is not None
        and runtime_mode is not payment_mode
    ):
        raise PaymentValidationError(
            "AUTONOMERCE_MODE conflicts with AUTONOMERCE_PAYMENT_MODE"
        )
    return runtime_mode or payment_mode or PaymentMode.OFFLINE


class PaymentAdapter:
    """Bridge the API lane's shared protocol to the guarded payment processor."""

    def __init__(
        self,
        *,
        mode: PaymentMode | str = PaymentMode.OFFLINE,
        store: PaymentStore | None = None,
        executor: CircleExecutor | None = None,
        maximum_per_payment_usdc: Decimal | str | int = "1000",
        maximum_total_usdc: Decimal | str | int = "10000",
        maximum_payment_count: int = 1000,
        allowed_chains: tuple[str, ...] | None = None,
        allowed_payer_wallets: tuple[str, ...] = (),
        allowed_payee_wallets: tuple[str, ...] = (),
        mainnet_enabled: bool = False,
        verification_hooks: tuple[ReceiptHook, ...] = (),
    ) -> None:
        self.mode = PaymentMode.parse(mode)
        self.maximum_per_payment_usdc = usdc(maximum_per_payment_usdc)
        self.maximum_total_usdc = usdc(maximum_total_usdc)
        self.maximum_payment_count = maximum_payment_count
        self.allowed_chains = tuple(
            canonical_chain(chain)
            for chain in (
                allowed_chains
                or (
                    ("ARC-TESTNET", "BASE-SEPOLIA", "BASE")
                    if self.mode is PaymentMode.OFFLINE
                    else (
                        ("ARC-TESTNET", "BASE-SEPOLIA")
                        if self.mode is PaymentMode.TESTNET
                        else ("BASE",)
                    )
                )
            )
        )
        self.allowed_payer_wallets = allowed_payer_wallets
        self.allowed_payee_wallets = allowed_payee_wallets
        self.mainnet_enabled = mainnet_enabled
        self.verification_hooks = tuple(verification_hooks)
        if self.mode.is_live and (
            not self.allowed_payer_wallets or not self.allowed_payee_wallets
        ):
            raise PaymentValidationError(
                "live payment adapter requires owner-configured payer and payee allowlists"
            )
        if self.mode.is_live and store is None:
            raise PaymentValidationError(
                "live payment adapter requires a durable idempotency store"
            )
        self.store = store or InMemoryPaymentStore()
        try:
            self.store_durability = StoreDurability(
                getattr(self.store, "durability")
            )
        except (AttributeError, ValueError) as exc:
            raise PaymentValidationError(
                "payment store must expose a recognized durability capability"
            ) from exc
        self.durability = self.store_durability
        if self.mode.is_live and not self.store_durability.is_durable:
            raise PaymentValidationError(
                "live payment adapter rejects process-local payment stores"
            )
        if self.mode.is_live and not has_independent_transaction_lookup(
            self.verification_hooks
        ):
            raise PaymentValidationError(
                "live payment adapter requires an independent transaction lookup hook"
            )
        self.independent_verification = (
            self.mode.is_live
            and has_independent_transaction_lookup(self.verification_hooks)
        )
        self.executor = executor or (
            OfflineCircleExecutor()
            if self.mode is PaymentMode.OFFLINE
            else CircleCLIExecutor(mode=self.mode)
        )
        if self.executor.mode is not self.mode:
            raise PaymentValidationError(
                "payment executor mode does not match adapter mode"
            )
        self.moves_funds = self.mode.is_live

    def execute_payment(
        self,
        proposal: Proposal,
        *,
        idempotency_key: str,
        chain: str,
        token: str,
        payer_wallet: str,
        payee_wallet: str,
        public: bool,
    ) -> PaymentExecution:
        payment_intent = PaymentIntent.from_proposal(
            proposal,
            idempotency_key=idempotency_key,
            chain=chain,
            token=token,
            payer_wallet=payer_wallet,
            payee_wallet=payee_wallet,
        )
        # Offline mode binds each API request to its exact wallets. Live modes use only
        # the owner-configured allowlists supplied at adapter construction.
        payer_allowlist = (
            self.allowed_payer_wallets
            if self.mode.is_live
            else (payment_intent.payer_wallet,)
        )
        payee_allowlist = (
            self.allowed_payee_wallets
            if self.mode.is_live
            else (payment_intent.payee_wallet,)
        )
        payment_policy = PaymentPolicy(
            policy_id=f"api-payment-{self.mode.value}",
            mode=self.mode,
            maximum_per_payment_usdc=self.maximum_per_payment_usdc,
            maximum_total_usdc=self.maximum_total_usdc,
            maximum_payment_count=self.maximum_payment_count,
            allowed_chains=self.allowed_chains,
            allowed_token="USDC",
            allowed_payer_wallets=payer_allowlist,
            allowed_payee_wallets=payee_allowlist,
            mainnet_enabled=self.mainnet_enabled,
        )
        receipt = PaymentProcessor(
            policy=payment_policy,
            store=self.store,
            executor=self.executor,
            verification_hooks=self.verification_hooks,
        ).pay(payment_intent)
        # Payment execution only creates immutable private financial records.
        # ``public`` remains in the shared protocol for compatibility, but receipt
        # publication must be a separate authenticated, durable action.
        _ = public
        return PaymentExecution(
            receipt=receipt,
            mocked=self.mode is PaymentMode.OFFLINE,
        )


def build_payment_adapter(
    environment: Mapping[str, str] | None = None,
    *,
    transaction_lookup: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> PaymentAdapter:
    """Build the configured adapter without accepting credentials through the API."""

    env = os.environ if environment is None else environment
    network = _supported_network(
        _configured_value(env, "AUTONOMERCE_CIRCLE_NETWORK")
    )
    mode = _environment_mode(env, network=network)
    per_payment = _configured_usdc(
        env,
        "AUTONOMERCE_CIRCLE_MAX_PER_TX_USDC",
        "AUTONOMERCE_PAYMENT_MAX_PER_PAYMENT_USDC",
        default="1000",
    )
    total = _configured_usdc(
        env,
        "AUTONOMERCE_CIRCLE_MAX_DAILY_USDC",
        "AUTONOMERCE_PAYMENT_MAX_TOTAL_USDC",
        default="10000",
    )
    count_text = _configured_value(
        env,
        "AUTONOMERCE_PAYMENT_MAX_COUNT",
        default="1000",
    )
    try:
        count = int(count_text)
    except (TypeError, ValueError) as exc:
        raise PaymentValidationError("invalid AUTONOMERCE_PAYMENT_MAX_COUNT") from exc
    configured_chains = _csv(env.get("AUTONOMERCE_PAYMENT_ALLOWED_CHAINS"))
    if configured_chains:
        configured_chains = tuple(
            dict.fromkeys(canonical_chain(chain) for chain in configured_chains)
        )
    if network is not None:
        if configured_chains and network not in configured_chains:
            raise PaymentValidationError(
                "AUTONOMERCE_CIRCLE_NETWORK conflicts with allowed payment chains"
            )
        if not configured_chains:
            configured_chains = (network,)

    payer_wallets = _csv(env.get("AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS"))
    documented_payer = _configured_value(
        env, "AUTONOMERCE_CIRCLE_WALLET_ADDRESS"
    )
    if documented_payer:
        if payer_wallets and tuple(
            wallet.lower() for wallet in payer_wallets
        ) != (documented_payer.lower(),):
            raise PaymentValidationError(
                "AUTONOMERCE_CIRCLE_WALLET_ADDRESS conflicts with payer allowlist"
            )
        payer_wallets = (documented_payer,)
    payee_wallets = _csv(env.get("AUTONOMERCE_PAYMENT_ALLOWED_PAYEE_WALLETS"))

    if mode is PaymentMode.OFFLINE:
        return PaymentAdapter(
            mode=mode,
            maximum_per_payment_usdc=per_payment,
            maximum_total_usdc=total,
            maximum_payment_count=count,
            allowed_chains=configured_chains or None,
        )

    lookup = transaction_lookup or _load_transaction_lookup(env)
    verification_hooks = (transaction_lookup_hook(lookup),)

    if not configured_chains:
        raise PaymentValidationError(
            "live modes require AUTONOMERCE_CIRCLE_NETWORK or "
            "AUTONOMERCE_PAYMENT_ALLOWED_CHAINS"
        )
    if mode is PaymentMode.TESTNET and any(
        not is_testnet_chain(chain) for chain in configured_chains
    ):
        raise PaymentValidationError(
            "testnet mode requires only testnet Circle networks"
        )
    if mode is PaymentMode.MAINNET and any(
        is_testnet_chain(chain) for chain in configured_chains
    ):
        raise PaymentValidationError(
            "mainnet mode requires only mainnet Circle networks"
        )

    database_path = env.get("AUTONOMERCE_PAYMENT_SQLITE_PATH", "").strip()
    if not database_path:
        raise PaymentValidationError(
            "live modes require AUTONOMERCE_PAYMENT_SQLITE_PATH"
        )
    if database_path == ":memory:" or database_path.startswith("file::memory:"):
        raise PaymentValidationError(
            "live modes reject in-memory SQLite payment stores"
        )
    store = SQLitePaymentStore(Path(database_path))
    mainnet_confirmation = env.get("AUTONOMERCE_ENABLE_MAINNET_PAYMENTS")
    mainnet_enabled = (
        mode is PaymentMode.MAINNET
        and mainnet_confirmation == MAINNET_CONFIRMATION
    )
    executor = CircleCLIExecutor(
        mode=mode,
        binary=env.get(
            "AUTONOMERCE_CIRCLE_CLI_BINARY",
            DEFAULT_CIRCLE_BINARY,
        ),
        allow_mainnet=mainnet_enabled,
        mainnet_confirmation=mainnet_confirmation,
        binary_sha256=env.get("AUTONOMERCE_CIRCLE_CLI_SHA256"),
    )
    return PaymentAdapter(
        mode=mode,
        store=store,
        executor=executor,
        maximum_per_payment_usdc=per_payment,
        maximum_total_usdc=total,
        maximum_payment_count=count,
        allowed_chains=configured_chains or None,
        allowed_payer_wallets=payer_wallets,
        allowed_payee_wallets=payee_wallets,
        mainnet_enabled=mainnet_enabled,
        verification_hooks=verification_hooks,
    )


get_payment_adapter = build_payment_adapter
