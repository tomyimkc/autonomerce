"""Deployable integration composition for Autonomerce runtime modes."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
import hashlib
import inspect
from importlib import import_module
import os
from typing import Any, Callable, Mapping, Protocol, Sequence

from autonomerce.contracts import (
    CapabilityDescriptor,
    CommercialPolicy,
    ContractError,
    PaymentReceipt,
    PaymentState,
    Proposal,
    ServiceSKU,
    stable_id,
    usdc,
)
from autonomerce.payments import KNOWN_USDC_ASSETS


_OFFLINE_TIMESTAMP = "2000-01-01T00:00:00+00:00"
_LIVE_PAYMENT_MODES = frozenset({"testnet", "mainnet"})


class AdapterConfigurationError(RuntimeError):
    """The requested runtime mode cannot be composed safely."""


class ProductizerAdapter(Protocol):
    def preview_skus(
        self,
        seller: Mapping[str, Any],
        capabilities: Sequence[CapabilityDescriptor],
        options: Mapping[str, Any],
    ) -> Sequence[ServiceSKU]:
        """Return shared-contract SKU candidates for the supplied capabilities."""


class PaymentAdapter(Protocol):
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
    ) -> "PaymentExecution | PaymentReceipt":
        """Settle one accepted proposal or return an idempotent prior receipt."""


class FulfillmentAdapter(Protocol):
    def fulfill(
        self,
        proposal: Proposal,
        *,
        artifact: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> "FulfillmentExecution | Mapping[str, Any]":
        """Invoke a seller agent without exposing private chain-of-thought."""


class SellerAgentExecutor(Protocol):
    def execute(
        self,
        proposal: Proposal,
        *,
        context: Mapping[str, Any],
    ) -> "FulfillmentExecution | Mapping[str, Any]":
        """Produce seller-authored output for one paid proposal."""


@dataclass(frozen=True)
class PaymentExecution:
    receipt: PaymentReceipt
    mocked: bool = False


@dataclass(frozen=True)
class FulfillmentExecution:
    artifact: Mapping[str, Any]
    acceptance_results: Mapping[str, bool] = field(default_factory=dict)
    validator: str = "contract-validator"
    delivered_at: str | None = None


class OfflineProductizer:
    """Credential-free deterministic SKU preview used by tests and demos."""

    def preview_skus(
        self,
        seller: Mapping[str, Any],
        capabilities: Sequence[CapabilityDescriptor],
        options: Mapping[str, Any],
    ) -> Sequence[ServiceSKU]:
        base_price = usdc(options.get("base_price_usdc", "1"))
        latency = int(options.get("maximum_latency_seconds", 300))
        capacity = int(options.get("capacity_per_hour", 1))
        variants = max(1, min(int(options.get("variants", 1)), 3))
        requested_criteria = tuple(options.get("acceptance_criteria", ()))
        tiers = (
            ("Basic", Decimal("1")),
            ("Plus", Decimal("2")),
            ("Priority", Decimal("3")),
        )
        skus: list[ServiceSKU] = []

        for capability in capabilities:
            criteria = list(requested_criteria or ("non_empty_artifact",))
            if capability.output_schema and "output_schema_valid" not in criteria:
                criteria.append("output_schema_valid")
            required = capability.output_schema.get("required", ())
            if isinstance(required, (list, tuple)):
                for field_name in required:
                    criterion = f"required_field:{str(field_name).strip()}"
                    if str(field_name).strip() and criterion not in criteria:
                        criteria.append(criterion)
            for tier_name, multiplier in tiers[:variants]:
                name = (
                    capability.name
                    if variants == 1
                    else f"{capability.name} {tier_name}"
                )
                price = base_price * multiplier
                sku_id = stable_id(
                    "sku",
                    seller["seller_id"],
                    capability.capability_id,
                    tier_name,
                    price,
                    latency,
                    capacity,
                )
                skus.append(
                    ServiceSKU(
                        sku_id=sku_id,
                        capability_id=capability.capability_id,
                        name=name,
                        outcome=capability.description,
                        base_price_usdc=price,
                        input_schema=capability.input_schema,
                        output_schema=capability.output_schema,
                        acceptance_criteria=tuple(criteria),
                        maximum_latency_seconds=latency,
                        capacity_per_hour=capacity,
                    )
                )
        return skus


class GeminiProductizerAdapter:
    """Use GeminiDecisionProvider and CapabilityProductizer without a fallback."""

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-flash",
        client: Any | None = None,
        provider: Any | None = None,
    ) -> None:
        if provider is not None and client is not None:
            raise ValueError("provide either a Gemini provider or client, not both")
        from autonomerce.agents import CapabilityProductizer, GeminiDecisionProvider

        self.provider = provider or GeminiDecisionProvider(model=model, client=client)
        self.productizer = CapabilityProductizer(self.provider)

    def preview_skus(
        self,
        seller: Mapping[str, Any],
        capabilities: Sequence[CapabilityDescriptor],
        options: Mapping[str, Any],
    ) -> Sequence[ServiceSKU]:
        base_price = usdc(options.get("base_price_usdc", "1"))
        latency_limit = int(options.get("maximum_latency_seconds", 300))
        capacity_limit = int(options.get("capacity_per_hour", 1))
        variants = max(1, min(int(options.get("variants", 1)), 3))
        requested_criteria = tuple(
            str(value).strip()
            for value in options.get("acceptance_criteria", ())
            if str(value).strip()
        )
        seller_id = str(seller.get("seller_id", "")).strip()
        if not seller_id:
            raise ContractError("seller_id is required for productization")
        network = str(seller.get("network", "ARC-TESTNET")).strip() or "ARC-TESTNET"
        policy = CommercialPolicy(
            policy_id=stable_id(
                "policy_preview",
                seller_id,
                base_price,
                variants,
                latency_limit,
                capacity_limit,
            ),
            owner_id=seller_id,
            minimum_price_usdc=base_price,
            maximum_price_usdc=base_price * variants,
            maximum_tasks_per_hour=capacity_limit,
            allowed_chains=(network,),
        )

        generated: list[ServiceSKU] = []
        for capability in capabilities:
            decision = self.productizer.productize(
                capability,
                policy,
                maximum_skus=variants,
            )
            for sku in decision.skus:
                criteria = list(sku.acceptance_criteria)
                for criterion in requested_criteria:
                    if criterion not in criteria:
                        criteria.append(criterion)
                generated.append(
                    replace(
                        sku,
                        acceptance_criteria=tuple(criteria),
                        maximum_latency_seconds=min(
                            sku.maximum_latency_seconds, latency_limit
                        ),
                        capacity_per_hour=min(
                            sku.capacity_per_hour, capacity_limit
                        ),
                    )
                )
        return generated


class MockPaymentAdapter:
    """A deterministic payment adapter that never contacts a wallet or network."""

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
        payment_id = stable_id("payment", proposal.proposal_id, idempotency_key)
        tx_digest = hashlib.sha256(
            f"{payment_id}:{chain}:{token}:{proposal.price_usdc}".encode("utf-8")
        ).hexdigest()
        receipt = PaymentReceipt(
            payment_id=payment_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=idempotency_key,
            state=PaymentState.CONFIRMED,
            amount_usdc=proposal.price_usdc,
            chain=chain,
            payer_wallet=payer_wallet,
            payee_wallet=payee_wallet,
            transaction_hash=f"0x{tx_digest}",
            explorer_url=None,
            confirmed_at=_OFFLINE_TIMESTAMP,
            public=public,
            token=token,
            asset=(
                KNOWN_USDC_ASSETS.get(chain.upper(), (None,))[0]
            ),
        )
        return PaymentExecution(receipt=receipt, mocked=True)


class OfflineFulfillmentAdapter:
    """Return deterministic fixture-like output without invoking a seller."""

    def fulfill(
        self,
        proposal: Proposal,
        *,
        artifact: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> FulfillmentExecution:
        del context
        output = dict(
            artifact
            or {
                "status": "fulfilled",
                "proposalId": proposal.proposal_id,
                "skuId": proposal.sku_id,
            }
        )
        acceptance_results: dict[str, bool] = {}
        for criterion in proposal.acceptance_criteria:
            if criterion == "non_empty_artifact":
                acceptance_results[criterion] = bool(output)
            elif criterion.startswith("required_field:"):
                field_name = criterion.split(":", 1)[1]
                acceptance_results[criterion] = field_name in output
        return FulfillmentExecution(
            artifact=output,
            acceptance_results=acceptance_results,
            validator="offline-contract-validator",
            delivered_at=_OFFLINE_TIMESTAMP,
        )


class SellerAgentFulfillmentAdapter:
    """Guard the live seller boundary and ignore caller-authored verdicts."""

    def __init__(self, executor: Any) -> None:
        if executor is None:
            raise AdapterConfigurationError(
                "live fulfillment requires a configured seller-agent executor"
            )
        self.executor = executor

    def fulfill(
        self,
        proposal: Proposal,
        *,
        artifact: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> FulfillmentExecution | Mapping[str, Any] | Any:
        if artifact is not None:
            raise ContractError(
                "live fulfillment does not accept caller-authored seller artifacts"
            )
        safe_context = {
            str(key): value
            for key, value in context.items()
            if str(key) != "acceptance_results"
        }
        method = getattr(self.executor, "execute", None)
        if not callable(method):
            method = getattr(self.executor, "fulfill", None)
        if not callable(method) and callable(self.executor):
            method = self.executor
        if not callable(method):
            raise AdapterConfigurationError(
                "seller-agent executor must expose execute(...) or fulfill(...)"
            )
        return _invoke_seller_executor(method, proposal, safe_context)


@dataclass(frozen=True)
class AdapterBundle:
    productizer: ProductizerAdapter = field(default_factory=OfflineProductizer)
    payment: PaymentAdapter = field(default_factory=MockPaymentAdapter)
    fulfillment: FulfillmentAdapter = field(default_factory=OfflineFulfillmentAdapter)
    sources: Mapping[str, Any] = field(
        default_factory=lambda: {
            "runtimeMode": "offline",
            "productizer": "offline:deterministic-rules-v1",
            "payment": "offline:mock",
            "paymentMode": "offline",
            "movesFunds": False,
            "fulfillment": "offline:deterministic",
        }
    )
    optional_import_errors: tuple[str, ...] = ()

    @property
    def diagnostics(self) -> Mapping[str, Any]:
        """Secret-free adapter facts suitable for a health response."""

        return dict(self.sources)


def _invoke_factory(
    factory: Callable[..., Any],
    environment: Mapping[str, str],
) -> Any:
    """Invoke an injected/imported factory without masking factory failures."""

    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory()
    parameters = signature.parameters
    if "environment" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return factory(environment=environment)
    positional = [
        parameter
        for parameter in parameters.values()
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    ]
    if positional and positional[0].default is inspect.Parameter.empty:
        return factory(environment)
    return factory()


def _invoke_seller_executor(
    method: Callable[..., Any],
    proposal: Proposal,
    context: Mapping[str, Any],
) -> Any:
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return method(proposal, context=context)
    kwargs: dict[str, Any] = {}
    if "artifact" in parameters:
        kwargs["artifact"] = None
    if "context" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        kwargs["context"] = context
    return method(proposal, **kwargs)


def _load_factory(
    path: str,
    *,
    module_loader: Callable[[str], Any],
) -> Callable[..., Any]:
    module_name: str
    attribute_name: str
    if ":" in path:
        module_name, attribute_name = path.rsplit(":", 1)
    elif "." in path:
        module_name, attribute_name = path.rsplit(".", 1)
    else:
        raise AdapterConfigurationError(
            "adapter factory must use package.module:factory syntax"
        )
    try:
        module = module_loader(module_name)
    except Exception as exc:
        raise AdapterConfigurationError(
            f"could not import configured adapter module ({type(exc).__name__})"
        ) from exc
    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise AdapterConfigurationError("configured adapter factory was not found")
    return factory


def _class_name(value: Any) -> str:
    cls = value.__class__
    return f"{cls.__module__}.{cls.__name__}"


def _payment_mode(value: Any) -> str | None:
    mode = getattr(value, "mode", None)
    if mode is None:
        return None
    raw = getattr(mode, "value", mode)
    normalized = str(raw).strip().lower()
    return normalized or None


def _runtime_modes(environment: Mapping[str, str]) -> tuple[str, str | None]:
    requested = str(environment.get("AUTONOMERCE_MODE", "offline")).strip().lower()
    if requested in {"offline", "gemini", "live"}:
        return requested, None
    if requested in _LIVE_PAYMENT_MODES:
        return "live", requested
    raise AdapterConfigurationError(
        "AUTONOMERCE_MODE must be offline, gemini, live, testnet, or mainnet"
    )


def _configured_payment_mode(
    environment: Mapping[str, str],
    forced_mode: str | None,
    *,
    infer_from_network: bool,
) -> str | None:
    explicit = str(environment.get("AUTONOMERCE_PAYMENT_MODE", "")).strip().lower()
    if explicit:
        if explicit not in {"offline", *_LIVE_PAYMENT_MODES}:
            raise AdapterConfigurationError(
                "AUTONOMERCE_PAYMENT_MODE must be offline, testnet, or mainnet"
            )
        if forced_mode and explicit != forced_mode:
            raise AdapterConfigurationError(
                "runtime mode conflicts with AUTONOMERCE_PAYMENT_MODE"
            )
        return explicit
    if forced_mode:
        network_mode = _payment_mode_from_network(environment)
        if network_mode and network_mode != forced_mode:
            raise AdapterConfigurationError(
                "runtime mode conflicts with AUTONOMERCE_CIRCLE_NETWORK"
            )
        return forced_mode
    if not infer_from_network:
        return None
    return _payment_mode_from_network(environment)


def _payment_mode_from_network(
    environment: Mapping[str, str],
) -> str | None:
    network = str(environment.get("AUTONOMERCE_CIRCLE_NETWORK", "")).strip().upper()
    if network in {"ARC-TESTNET", "BASE-SEPOLIA"}:
        return "testnet"
    if network in {"BASE", "BASE-MAINNET"}:
        return "mainnet"
    return None


def _payment_environment(
    environment: Mapping[str, str],
    *,
    payment_mode: str,
) -> dict[str, str]:
    """Bridge documented Circle names to the guarded payment-lane factory."""

    configured = dict(environment)
    configured["AUTONOMERCE_PAYMENT_MODE"] = payment_mode
    aliases = {
        "AUTONOMERCE_PAYMENT_MAX_PER_PAYMENT_USDC": (
            "AUTONOMERCE_CIRCLE_MAX_PER_TX_USDC"
        ),
        "AUTONOMERCE_PAYMENT_MAX_TOTAL_USDC": (
            "AUTONOMERCE_CIRCLE_MAX_DAILY_USDC"
        ),
    }
    for target, source in aliases.items():
        if not str(configured.get(target, "")).strip() and str(
            configured.get(source, "")
        ).strip():
            configured[target] = configured[source]
    if not str(configured.get("AUTONOMERCE_PAYMENT_ALLOWED_CHAINS", "")).strip():
        network = str(configured.get("AUTONOMERCE_CIRCLE_NETWORK", "")).strip()
        if network:
            configured["AUTONOMERCE_PAYMENT_ALLOWED_CHAINS"] = network
    return configured


def _build_live_payment(
    environment: Mapping[str, str],
    *,
    payment_mode: str,
    payment_adapter: Any | None,
    payment_factory: Callable[..., Any] | None,
    module_loader: Callable[[str], Any],
) -> Any:
    if payment_adapter is not None and payment_factory is not None:
        raise AdapterConfigurationError(
            "provide either a payment adapter or payment factory, not both"
        )
    configured = _payment_environment(
        environment,
        payment_mode=payment_mode,
    )
    try:
        if payment_adapter is not None:
            adapter = payment_adapter
        else:
            factory = payment_factory
            factory_path = str(
                environment.get("AUTONOMERCE_PAYMENT_ADAPTER_FACTORY", "")
            ).strip()
            if factory is None and factory_path:
                factory = _load_factory(factory_path, module_loader=module_loader)
            if factory is None:
                module = module_loader("autonomerce.payments.api_adapter")
                factory = getattr(module, "build_payment_adapter", None)
                if not callable(factory):
                    raise AdapterConfigurationError(
                        "live payment adapter factory was not found"
                    )
            adapter = _invoke_factory(factory, configured)
    except AdapterConfigurationError:
        raise
    except Exception as exc:
        raise AdapterConfigurationError(
            f"live payment adapter failed to load ({type(exc).__name__})"
        ) from exc

    actual_mode = _payment_mode(adapter)
    if (
        isinstance(adapter, MockPaymentAdapter)
        or actual_mode not in _LIVE_PAYMENT_MODES
    ):
        raise AdapterConfigurationError(
            "requested live payment mode resolved to an offline or unknown adapter"
        )
    if actual_mode != payment_mode:
        raise AdapterConfigurationError(
            "loaded payment adapter mode does not match requested live mode"
        )
    if not bool(getattr(adapter, "independent_verification", False)):
        raise AdapterConfigurationError(
            "live payment adapter must require independent transaction verification"
        )
    return adapter


def _build_seller_executor(
    environment: Mapping[str, str],
    *,
    seller_agent_executor: Any | None,
    seller_executor_factory: Callable[..., Any] | None,
    module_loader: Callable[[str], Any],
) -> Any:
    if seller_agent_executor is not None and seller_executor_factory is not None:
        raise AdapterConfigurationError(
            "provide either a seller executor or seller executor factory, not both"
        )
    if seller_agent_executor is not None:
        return seller_agent_executor
    factory = seller_executor_factory
    factory_path = (
        str(
            environment.get("AUTONOMERCE_SELLER_EXECUTOR_FACTORY", "")
        ).strip()
        or str(
            environment.get("AUTONOMERCE_FULFILLMENT_ADAPTER_FACTORY", "")
        ).strip()
    )
    if factory is None and factory_path:
        factory = _load_factory(factory_path, module_loader=module_loader)
    if factory is None:
        raise AdapterConfigurationError(
            "live fulfillment requires AUTONOMERCE_SELLER_EXECUTOR_FACTORY "
            "or an injected seller-agent executor"
        )
    try:
        executor = _invoke_factory(factory, environment)
    except Exception as exc:
        raise AdapterConfigurationError(
            f"seller-agent executor failed to load ({type(exc).__name__})"
        ) from exc
    if executor is None:
        raise AdapterConfigurationError(
            "seller-agent executor factory returned no executor"
        )
    return executor


def load_optional_adapters(
    environment: Mapping[str, str] | None = None,
    *,
    gemini_client: Any | None = None,
    gemini_provider: Any | None = None,
    payment_adapter: Any | None = None,
    payment_factory: Callable[..., Any] | None = None,
    seller_agent_executor: Any | None = None,
    seller_executor_factory: Callable[..., Any] | None = None,
    module_loader: Callable[[str], Any] = import_module,
) -> AdapterBundle:
    """Compose the explicitly requested mode; never downgrade it silently.

    ``offline`` is entirely deterministic and imports no optional integration
    lane. ``gemini`` uses the real Gemini decision/provider boundary while keeping
    payment and fulfillment offline. ``live`` requires Gemini, a non-offline
    payment adapter, and an explicitly configured seller-agent executor.
    """

    env = dict(os.environ if environment is None else environment)
    runtime_mode, forced_payment_mode = _runtime_modes(env)
    requested_payment_mode = _configured_payment_mode(
        env,
        forced_payment_mode,
        infer_from_network=runtime_mode == "live",
    )
    explicit_productizer_mode = str(
        env.get("AUTONOMERCE_PRODUCTIZER_MODE", "")
    ).strip().lower()
    expected_productizer_mode = (
        "offline" if runtime_mode == "offline" else "gemini"
    )
    if explicit_productizer_mode and (
        explicit_productizer_mode != expected_productizer_mode
    ):
        raise AdapterConfigurationError(
            "AUTONOMERCE_PRODUCTIZER_MODE conflicts with AUTONOMERCE_MODE"
        )

    if runtime_mode != "live" and requested_payment_mode in _LIVE_PAYMENT_MODES:
        raise AdapterConfigurationError(
            "live payment mode was requested while AUTONOMERCE_MODE is not live"
        )

    if runtime_mode == "offline":
        return AdapterBundle()

    model = str(env.get("AUTONOMERCE_GEMINI_MODEL", "")).strip()
    productizer = GeminiProductizerAdapter(
        model=model or "gemini-2.5-flash",
        client=gemini_client,
        provider=gemini_provider,
    )
    provider_name = str(
        getattr(productizer.provider, "provider_name", "google")
    ).strip()
    model_name = str(
        getattr(productizer.provider, "model_name", model or "gemini-2.5-flash")
    ).strip()

    if runtime_mode == "gemini":
        return AdapterBundle(
            productizer=productizer,
            payment=MockPaymentAdapter(),
            fulfillment=OfflineFulfillmentAdapter(),
            sources={
                "runtimeMode": "gemini",
                "productizer": f"{provider_name}:{model_name}",
                "payment": "offline:mock",
                "paymentMode": "offline",
                "movesFunds": False,
                "fulfillment": "offline:deterministic",
            },
        )

    if requested_payment_mode not in _LIVE_PAYMENT_MODES:
        raise AdapterConfigurationError(
            "live mode requires an explicit testnet or mainnet payment mode/network"
        )
    payment = _build_live_payment(
        env,
        payment_mode=requested_payment_mode,
        payment_adapter=payment_adapter,
        payment_factory=payment_factory,
        module_loader=module_loader,
    )
    seller_executor = _build_seller_executor(
        env,
        seller_agent_executor=seller_agent_executor,
        seller_executor_factory=seller_executor_factory,
        module_loader=module_loader,
    )
    fulfillment = SellerAgentFulfillmentAdapter(seller_executor)
    return AdapterBundle(
        productizer=productizer,
        payment=payment,
        fulfillment=fulfillment,
        sources={
            "runtimeMode": "live",
            "productizer": f"{provider_name}:{model_name}",
            "payment": _class_name(payment),
            "paymentMode": requested_payment_mode,
            "movesFunds": True,
            "fulfillment": _class_name(seller_executor),
        },
    )
