"""Deterministic in-process request rate and concurrency limits.

The API is explicitly single-owner today, but limits are maintained separately
for the authenticated owner and the direct ASGI peer address.  Forwarded
headers are deliberately ignored because trusting them belongs at a configured
reverse-proxy boundary.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import math
import time
from typing import Callable


@dataclass(frozen=True)
class RouteBudget:
    """A sliding-window request budget and an in-flight concurrency budget."""

    owner_requests: int
    ip_requests: int
    window_seconds: float
    owner_concurrency: int
    ip_concurrency: int

    def __post_init__(self) -> None:
        values = (
            self.owner_requests,
            self.ip_requests,
            self.window_seconds,
            self.owner_concurrency,
            self.ip_concurrency,
        )
        if any(value <= 0 for value in values):
            raise ValueError("rate-limit budgets must be positive")


@dataclass(frozen=True)
class RateLimitPolicy:
    """Route-class budgets, with smaller limits for expensive operations."""

    standard: RouteBudget = RouteBudget(
        owner_requests=120,
        ip_requests=240,
        window_seconds=60,
        owner_concurrency=16,
        ip_concurrency=32,
    )
    gemini: RouteBudget = RouteBudget(
        owner_requests=20,
        ip_requests=40,
        window_seconds=60,
        owner_concurrency=2,
        ip_concurrency=4,
    )
    payment: RouteBudget = RouteBudget(
        owner_requests=10,
        ip_requests=20,
        window_seconds=60,
        owner_concurrency=1,
        ip_concurrency=2,
    )
    fulfillment: RouteBudget = RouteBudget(
        owner_requests=10,
        ip_requests=20,
        window_seconds=60,
        owner_concurrency=2,
        ip_concurrency=4,
    )

    def classify(self, method: str, path: str) -> tuple[str, RouteBudget]:
        normalized_method = method.upper()
        if normalized_method == "POST" and path.endswith("/pay"):
            return "payment", self.payment
        if normalized_method == "POST" and path.endswith("/fulfill"):
            return "fulfillment", self.fulfillment
        parts = [part for part in path.split("/") if part]
        if (
            normalized_method == "POST"
            and len(parts) == 4
            and parts[0] == "sellers"
            and parts[2:] == ["skus", "preview"]
        ):
            return "gemini", self.gemini
        return "standard", self.standard


class RateLimitExceeded(RuntimeError):
    """Raised with response-safe, deterministic rate-limit information."""

    def __init__(self, detail: str, retry_after: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after = max(1, retry_after)


class RateLimitLease:
    """An idempotently releasable in-flight concurrency reservation."""

    def __init__(
        self,
        limiter: "RequestLimiter",
        concurrency_keys: tuple[tuple[str, str, str], ...],
    ) -> None:
        self._limiter = limiter
        self._concurrency_keys = concurrency_keys
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._limiter._release(self._concurrency_keys)

    async def __aenter__(self) -> "RateLimitLease":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.release()


class RequestLimiter:
    """Apply owner and direct-peer limits atomically for each request."""

    def __init__(
        self,
        *,
        policy: RateLimitPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        maximum_tracked_identities: int = 4096,
    ) -> None:
        if maximum_tracked_identities < 2:
            raise ValueError(
                "maximum_tracked_identities must allow owner and IP keys"
            )
        self.policy = policy or RateLimitPolicy()
        self._clock = clock
        self._maximum_tracked_identities = maximum_tracked_identities
        self._maximum_window_seconds = max(
            budget.window_seconds
            for budget in (
                self.policy.standard,
                self.policy.gemini,
                self.policy.payment,
                self.policy.fulfillment,
            )
        )
        self._lock = asyncio.Lock()
        self._history: dict[tuple[str, str, str], deque[float]] = {}
        self._active: dict[tuple[str, str, str], int] = {}

    @property
    def tracked_identity_count(self) -> int:
        return len(self._history)

    def _sweep_expired_histories(self, now: float) -> None:
        cutoff = now - self._maximum_window_seconds
        for key, history in tuple(self._history.items()):
            while history and history[0] <= cutoff:
                history.popleft()
            if not history and self._active.get(key, 0) == 0:
                self._history.pop(key, None)

    async def acquire(
        self,
        *,
        owner_id: str | None,
        ip_address: str | None,
        method: str,
        path: str,
    ) -> RateLimitLease:
        route_class, budget = self.policy.classify(method, path)
        owner = (owner_id or "anonymous").strip() or "anonymous"
        peer = (ip_address or "unknown").strip() or "unknown"
        keys = (
            ("owner", owner, route_class),
            ("ip", peer, route_class),
        )
        request_limits = (budget.owner_requests, budget.ip_requests)
        concurrency_limits = (
            budget.owner_concurrency,
            budget.ip_concurrency,
        )
        now = self._clock()
        cutoff = now - budget.window_seconds

        async with self._lock:
            self._sweep_expired_histories(now)
            new_keys = [key for key in keys if key not in self._history]
            if (
                len(self._history) + len(new_keys)
                > self._maximum_tracked_identities
            ):
                raise RateLimitExceeded(
                    "request identity tracking limit exceeded",
                    math.ceil(self._maximum_window_seconds),
                )
            histories: list[deque[float]] = []
            for key, limit in zip(keys, request_limits, strict=True):
                history = self._history.setdefault(key, deque())
                while history and history[0] <= cutoff:
                    history.popleft()
                histories.append(history)
                if len(history) >= limit:
                    retry_after = math.ceil(
                        max(0.0, history[0] + budget.window_seconds - now)
                    )
                    raise RateLimitExceeded(
                        "request rate limit exceeded",
                        retry_after,
                    )

            for key, limit in zip(keys, concurrency_limits, strict=True):
                if self._active.get(key, 0) >= limit:
                    raise RateLimitExceeded(
                        "request concurrency limit exceeded",
                        1,
                    )

            for history in histories:
                history.append(now)
            for key in keys:
                self._active[key] = self._active.get(key, 0) + 1

        return RateLimitLease(self, keys)

    async def _release(
        self, concurrency_keys: tuple[tuple[str, str, str], ...]
    ) -> None:
        async with self._lock:
            for key in concurrency_keys:
                remaining = self._active.get(key, 0) - 1
                if remaining > 0:
                    self._active[key] = remaining
                else:
                    self._active.pop(key, None)
