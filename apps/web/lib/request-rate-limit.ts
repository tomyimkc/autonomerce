export class RequestRateLimitError extends Error {
  constructor(
    message: string,
    readonly retryAfterSeconds: number,
    readonly code = "rate_limited",
  ) {
    super(message);
    this.name = "RequestRateLimitError";
  }
}

function requireInteger(
  value: number,
  label: string,
  minimum: number,
): void {
  if (!Number.isInteger(value) || value < minimum) {
    throw new RangeError(`${label} must be an integer >= ${minimum}`);
  }
}

interface LoginAttemptState {
  failures: number;
  windowStartedAt: number;
  blockedUntil: number;
}

interface GlobalBudgetState {
  count: number;
  windowStartedAt: number;
}

export class OwnerLoginRateLimiter {
  private readonly attempts = new Map<string, LoginAttemptState>();
  private globalAttempts: GlobalBudgetState | null = null;

  constructor(
    private readonly windowMs = 15 * 60 * 1_000,
    private readonly maximumFailures = 10,
    private readonly maximumBackoffMs = 5 * 60 * 1_000,
    private readonly maximumGlobalAttempts = 100,
    private readonly maximumTrackedAddresses = 1_024,
  ) {
    requireInteger(windowMs, "windowMs", 1);
    requireInteger(maximumFailures, "maximumFailures", 1);
    requireInteger(maximumBackoffMs, "maximumBackoffMs", 1);
    requireInteger(
      maximumGlobalAttempts,
      "maximumGlobalAttempts",
      1,
    );
    requireInteger(
      maximumTrackedAddresses,
      "maximumTrackedAddresses",
      1,
    );
  }

  get trackedAddressCount(): number {
    return this.attempts.size;
  }

  assertAllowed(address: string, nowMs = Date.now()): void {
    this.sweepExpired(nowMs);
    const state = this.attempts.get(address);
    if (state && state.failures >= this.maximumFailures) {
      throw this.limitError(
        state.windowStartedAt + this.windowMs - nowMs,
      );
    }
    if (state && state.blockedUntil > nowMs) {
      throw this.limitError(state.blockedUntil - nowMs);
    }

    const globalState = this.activeGlobalState(nowMs) ?? {
      count: 0,
      windowStartedAt: nowMs,
    };
    if (globalState.count >= this.maximumGlobalAttempts) {
      throw this.limitError(
        globalState.windowStartedAt + this.windowMs - nowMs,
      );
    }
    globalState.count += 1;
    this.globalAttempts = globalState;
  }

  recordFailure(address: string, nowMs = Date.now()): void {
    this.sweepExpired(nowMs);

    const existing = this.attempts.get(address);
    if (!existing && this.attempts.size >= this.maximumTrackedAddresses) {
      return;
    }
    const current = existing ?? {
      failures: 0,
      windowStartedAt: nowMs,
      blockedUntil: nowMs,
    };
    const failures = current.failures + 1;
    const backoffMs = Math.min(
      this.maximumBackoffMs,
      1_000 * 2 ** Math.min(failures - 1, 12),
    );
    this.attempts.set(address, {
      failures,
      windowStartedAt: current.windowStartedAt,
      blockedUntil: nowMs + backoffMs,
    });
  }

  recordSuccess(address: string): void {
    this.attempts.delete(address);
  }

  private sweepExpired(nowMs: number): void {
    for (const [address, state] of this.attempts) {
      if (state.windowStartedAt + this.windowMs <= nowMs) {
        this.attempts.delete(address);
      }
    }
    if (
      this.globalAttempts &&
      this.globalAttempts.windowStartedAt + this.windowMs <= nowMs
    ) {
      this.globalAttempts = null;
    }
  }

  private activeGlobalState(nowMs: number): GlobalBudgetState | null {
    if (
      this.globalAttempts &&
      this.globalAttempts.windowStartedAt + this.windowMs > nowMs
    ) {
      return this.globalAttempts;
    }
    this.globalAttempts = null;
    return null;
  }

  private limitError(waitMs: number): RequestRateLimitError {
    return new RequestRateLimitError(
      "Too many owner login attempts. Wait before retrying.",
      Math.max(1, Math.ceil(waitMs / 1_000)),
      "owner_login_rate_limited",
    );
  }
}

interface PublicRequestState {
  count: number;
  windowStartedAt: number;
}

export class PublicStatusBroker<T> {
  private readonly requests = new Map<string, PublicRequestState>();
  private globalRequests: GlobalBudgetState | null = null;
  private cache: { value: T; expiresAt: number } | null = null;
  private inFlight: Promise<T> | null = null;

  constructor(
    private readonly cacheTtlMs = 5_000,
    private readonly requestWindowMs = 60_000,
    private readonly maximumRequestsPerAddress = 60,
    private readonly maximumGlobalRequests = 600,
    private readonly maximumTrackedAddresses = 2_048,
  ) {
    requireInteger(cacheTtlMs, "cacheTtlMs", 0);
    requireInteger(requestWindowMs, "requestWindowMs", 1);
    requireInteger(
      maximumRequestsPerAddress,
      "maximumRequestsPerAddress",
      1,
    );
    requireInteger(
      maximumGlobalRequests,
      "maximumGlobalRequests",
      1,
    );
    requireInteger(
      maximumTrackedAddresses,
      "maximumTrackedAddresses",
      1,
    );
  }

  get trackedAddressCount(): number {
    return this.requests.size;
  }

  async get(
    address: string,
    loader: () => Promise<T>,
    nowMs = Date.now(),
  ): Promise<{ value: T; cache: "hit" | "miss" | "coalesced" }> {
    this.consume(address, nowMs);
    if (this.cache && this.cache.expiresAt > nowMs) {
      return { value: this.cache.value, cache: "hit" };
    }
    if (this.inFlight) {
      return { value: await this.inFlight, cache: "coalesced" };
    }

    const load = loader();
    this.inFlight = load;
    try {
      const value = await load;
      this.cache = {
        value,
        expiresAt: Date.now() + this.cacheTtlMs,
      };
      return { value, cache: "miss" };
    } finally {
      if (this.inFlight === load) {
        this.inFlight = null;
      }
    }
  }

  private consume(address: string, nowMs: number): void {
    this.sweepExpired(nowMs);

    const globalState = this.activeGlobalState(nowMs) ?? {
      count: 0,
      windowStartedAt: nowMs,
    };
    if (globalState.count >= this.maximumGlobalRequests) {
      throw this.limitError(
        globalState.windowStartedAt + this.requestWindowMs - nowMs,
      );
    }

    const existing = this.requests.get(address);
    const state =
      existing &&
      existing.windowStartedAt + this.requestWindowMs > nowMs
        ? existing
        : { count: 0, windowStartedAt: nowMs };
    if (state.count >= this.maximumRequestsPerAddress) {
      throw this.limitError(
        state.windowStartedAt + this.requestWindowMs - nowMs,
      );
    }

    globalState.count += 1;
    this.globalRequests = globalState;
    state.count += 1;
    if (existing || this.requests.size < this.maximumTrackedAddresses) {
      this.requests.set(address, state);
    }
  }

  private sweepExpired(nowMs: number): void {
    for (const [address, state] of this.requests) {
      if (state.windowStartedAt + this.requestWindowMs <= nowMs) {
        this.requests.delete(address);
      }
    }
    if (
      this.globalRequests &&
      this.globalRequests.windowStartedAt + this.requestWindowMs <=
        nowMs
    ) {
      this.globalRequests = null;
    }
  }

  private activeGlobalState(nowMs: number): GlobalBudgetState | null {
    if (
      this.globalRequests &&
      this.globalRequests.windowStartedAt + this.requestWindowMs > nowMs
    ) {
      return this.globalRequests;
    }
    this.globalRequests = null;
    return null;
  }

  private limitError(waitMs: number): RequestRateLimitError {
    return new RequestRateLimitError(
      "Public status request limit exceeded",
      Math.max(1, Math.ceil(waitMs / 1_000)),
      "public_status_rate_limited",
    );
  }
}
