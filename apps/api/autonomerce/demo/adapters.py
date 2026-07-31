"""Late-bound adapters for parallel Autonomerce implementation lanes.

The demo package imports only the shared contracts at module-import time.  Agents,
payments, sales, and OfferRail are discovered when a scenario starts, so this lane
can be imported and tested while sibling modules are still landing.  Once present,
the real lane implementations are used directly and reported in the demo receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping


class LaneUnavailableError(RuntimeError):
    """One or more required integration lanes are not importable yet."""


_LANE_MODULES = {
    "agents": "autonomerce.agents",
    "payments": "autonomerce.payments",
    "sales": "autonomerce.sales",
    "offerrail": "offerrail",
}


def _repo_local_packages() -> Path:
    return Path(__file__).resolve().parents[4] / "packages"


@dataclass(frozen=True)
class LaneBindings:
    """Resolved module boundaries for one integration run."""

    agents: ModuleType | None = None
    payments: ModuleType | None = None
    sales: ModuleType | None = None
    offerrail: ModuleType | None = None
    errors: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def discover(cls) -> "LaneBindings":
        modules: dict[str, ModuleType | None] = {}
        errors: dict[str, str] = {}
        for lane, module_name in _LANE_MODULES.items():
            try:
                modules[lane] = importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                # A repo checkout does not install packages/offerrail through the
                # API package's setuptools config.  Add only that known local parent
                # and retry; this remains credential-free and performs no network I/O.
                local_packages = _repo_local_packages()
                if lane == "offerrail" and local_packages.is_dir():
                    package_path = str(local_packages)
                    if package_path not in sys.path:
                        sys.path.insert(0, package_path)
                    try:
                        modules[lane] = importlib.import_module(module_name)
                        continue
                    except (ImportError, AttributeError) as retry_exc:
                        exc = retry_exc
                modules[lane] = None
                errors[lane] = f"{type(exc).__name__}: {exc}"
            except (ImportError, AttributeError) as exc:
                modules[lane] = None
                errors[lane] = f"{type(exc).__name__}: {exc}"
        return cls(errors=errors, **modules)

    @property
    def missing_lanes(self) -> tuple[str, ...]:
        return tuple(
            lane for lane in _LANE_MODULES if getattr(self, lane) is None
        )

    @property
    def available_lanes(self) -> tuple[str, ...]:
        return tuple(
            lane for lane in _LANE_MODULES if getattr(self, lane) is not None
        )

    def require_all(self) -> "LaneBindings":
        if self.missing_lanes:
            detail = "; ".join(
                f"{lane}: {self.errors.get(lane, 'not importable')}"
                for lane in self.missing_lanes
            )
            raise LaneUnavailableError(
                "offline demo requires all integration lanes; " + detail
            )
        return self

    def require(self, lane: str) -> ModuleType:
        if lane not in _LANE_MODULES:
            raise LaneUnavailableError(f"unknown integration lane: {lane}")
        module = getattr(self, lane)
        if module is None:
            raise LaneUnavailableError(
                f"integration lane {lane!r} is unavailable: "
                f"{self.errors.get(lane, 'not importable')}"
            )
        return module


def implementation_path(value: object) -> str:
    """Return a stable implementation name for public demo diagnostics."""

    selected = value if isinstance(value, type) else value.__class__
    return f"{selected.__module__}.{selected.__qualname__}"


class AgentDeliveryValidatorAdapter:
    """Adapt the agents delivery gate to the sales fulfillment protocol."""

    def __init__(
        self,
        *,
        sales_module: ModuleType,
        validator: Any,
        sku: Any,
        payment: Any,
        delivered_at: str,
    ) -> None:
        self._sales = sales_module
        self._validator = validator
        self._sku = sku
        self._payment = payment
        self._delivered_at = delivered_at
        self.last_decision: Any | None = None

    @property
    def backend(self) -> Any:
        return self._validator

    def validate(self, artifact: Any, proposal: Any) -> Any:
        decision = self._validator.validate(
            sku=self._sku,
            proposal=proposal,
            payment=self._payment,
            artifact=artifact,
            delivered_at=self._delivered_at,
        )
        self.last_decision = decision
        reason_code = (
            "accepted"
            if decision.accepted
            else (
                str(decision.reason_codes[0]).lower()
                if decision.reason_codes
                else "contract_validation_failed"
            )
        )
        return self._sales.ValidationResult(
            accepted=decision.accepted,
            acceptance_results=dict(
                decision.receipt.acceptance_results
            ),
            reason_code=reason_code,
        )
