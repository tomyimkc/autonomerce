import assert from "node:assert/strict";
import test from "node:test";

import {
  OwnerLoginRateLimiter,
  PublicStatusBroker,
  RequestRateLimitError,
} from "../lib/request-rate-limit";
import {
  InputValidationError,
  parseWorkflowInput,
} from "../lib/input-validation";

test("owner login limiter applies backoff and a bounded failure window", () => {
  const limiter = new OwnerLoginRateLimiter(10_000, 2, 5_000);

  limiter.recordFailure("203.0.113.10", 1_000);
  assert.throws(
    () => limiter.assertAllowed("203.0.113.10", 1_000),
    (error: unknown) =>
      error instanceof RequestRateLimitError &&
      error.code === "owner_login_rate_limited" &&
      error.retryAfterSeconds === 1,
  );

  limiter.assertAllowed("203.0.113.10", 2_000);
  limiter.recordFailure("203.0.113.10", 2_000);
  assert.throws(
    () => limiter.assertAllowed("203.0.113.10", 4_000),
    (error: unknown) =>
      error instanceof RequestRateLimitError &&
      error.code === "owner_login_rate_limited",
  );

  limiter.assertAllowed("203.0.113.10", 11_001);
});

test("owner login limiter globally blocks address rotation and bounds tracked state", () => {
  const limiter = new OwnerLoginRateLimiter(
    10_000,
    10,
    5_000,
    3,
    2,
  );

  for (const [address, nowMs] of [
    ["203.0.113.1", 1_000],
    ["203.0.113.2", 1_001],
    ["203.0.113.3", 1_002],
  ] as const) {
    limiter.assertAllowed(address, nowMs);
    limiter.recordFailure(address, nowMs);
  }

  assert.equal(limiter.trackedAddressCount, 2);
  assert.throws(
    () => limiter.assertAllowed("203.0.113.4", 1_003),
    (error: unknown) =>
      error instanceof RequestRateLimitError &&
      error.code === "owner_login_rate_limited",
  );

  limiter.assertAllowed("203.0.113.4", 11_001);
  assert.equal(limiter.trackedAddressCount, 0);
});

test("public status broker caches/coalesces and rate-limits by address", async () => {
  const broker = new PublicStatusBroker<{ status: string }>(
    60_000,
    10_000,
    2,
  );
  let loads = 0;
  const loader = async () => {
    loads += 1;
    return { status: "ok" };
  };

  const first = await broker.get("203.0.113.20", loader, 1_000);
  const second = await broker.get("203.0.113.20", loader, 1_001);

  assert.equal(first.cache, "miss");
  assert.equal(second.cache, "hit");
  assert.equal(loads, 1);
  await assert.rejects(
    broker.get("203.0.113.20", loader, 1_002),
    (error: unknown) =>
      error instanceof RequestRateLimitError &&
      error.code === "public_status_rate_limited",
  );
});

test("public status broker coalesces concurrent cache misses", async () => {
  const broker = new PublicStatusBroker<{ status: string }>(
    60_000,
    10_000,
    10,
  );
  let loads = 0;
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const loader = async () => {
    loads += 1;
    await gate;
    return { status: "ok" };
  };

  const first = broker.get("203.0.113.30", loader, 1_000);
  const second = broker.get("203.0.113.31", loader, 1_001);
  release?.();

  assert.equal((await first).cache, "miss");
  assert.equal((await second).cache, "coalesced");
  assert.equal(loads, 1);
});

test("public status broker globally blocks rotation and expiry-sweeps bounded state", async () => {
  const broker = new PublicStatusBroker<{ status: string }>(
    0,
    10_000,
    10,
    3,
    2,
  );
  const loader = async () => ({ status: "ok" });

  await broker.get("203.0.113.40", loader, 1_000);
  await broker.get("203.0.113.41", loader, 1_001);
  await broker.get("203.0.113.42", loader, 1_002);

  assert.equal(broker.trackedAddressCount, 2);
  await assert.rejects(
    broker.get("203.0.113.43", loader, 1_003),
    (error: unknown) =>
      error instanceof RequestRateLimitError &&
      error.code === "public_status_rate_limited",
  );

  await broker.get("203.0.113.43", loader, 11_001);
  assert.equal(broker.trackedAddressCount, 1);
});

test("workflow publication authorization must be explicit and separate", () => {
  const consentReference = "consent:buyer-contact:v1";
  assert.throws(
    () =>
      parseWorkflowInput({
        onboarding: {
          sellerId: "seller_1",
          skuId: "sku_1",
          policyId: "policy_1",
        },
        ownerWorkflowOperationId:
          "00000000-0000-4000-8000-000000000001",
        operationExpiresAt: new Date(
          Date.now() + 60 * 60 * 1_000,
        ).toISOString(),
        buyerAgentUrl: "https://buyer.example/agent",
        buyerOptInConfirmed: true,
        consentReference,
        publicationAuthorized: true,
        publicationConsentReference: consentReference,
        desiredOutcome: "Verify one claim",
        maximumPriceUsdc: "2",
        problemObserved: "A claim needs verification",
        offerPriceUsdc: "1",
        counterPriceUsdc: "0.9",
        deliverySeconds: 120,
      }),
    (error: unknown) =>
      error instanceof InputValidationError &&
      error.message.includes("must be distinct"),
  );
});
