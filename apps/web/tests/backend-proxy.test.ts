import assert from "node:assert/strict";
import test from "node:test";

import {
  AutonomerceService,
  workflowOperationFingerprint,
} from "../lib/autonomerce-service";
import {
  BACKEND_DEFAULT_TIMEOUT_MS,
  BACKEND_FULFILL_TIMEOUT_MS,
  BACKEND_IAM_TOKEN_TIMEOUT_MS,
  BACKEND_MAX_TIMEOUT_MS,
  BACKEND_PAY_TIMEOUT_MS,
  BackendClient,
  BackendRequestError,
  resolveBackendIamAuth,
  resolveBackendBaseUrl,
  type BackendRequestOptions,
} from "../lib/backend-core";
import { readProtectedJson } from "../lib/request-guards";

const TOKEN = "server-only-test-token";

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function googleIdToken(
  audience: string,
  claims: Record<string, unknown> = {},
): string {
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
  return [
    encode({ alg: "RS256", typ: "JWT" }),
    encode({
      iss: "https://accounts.google.com",
      aud: audience,
      exp: Math.floor(Date.now() / 1_000) + 3_600,
      sub: "1234567890",
      ...claims,
    }),
    "google-signature",
  ].join(".");
}

test("disabled IAM auth attaches only the application bearer server-side", async () => {
  let observedUrl = "";
  let observedAuthorization = "";
  let observedServerlessAuthorization: string | null = null;
  const client = new BackendClient(
    {
      baseUrl: "https://private-api.example",
      bearerToken: TOKEN,
      iamAuth: { enabled: false },
    },
    async (input, init) => {
      observedUrl = String(input);
      observedAuthorization = new Headers(init?.headers).get("authorization") ?? "";
      observedServerlessAuthorization = new Headers(init?.headers).get(
        "x-serverless-authorization",
      );
      return json({
        status: "ok",
        service: "autonomerce-api",
        storage: "memory",
        paymentMode: "mock",
        movesFunds: false,
      });
    },
  );

  await client.get("/health");
  assert.equal(observedUrl, "https://private-api.example/health");
  assert.equal(observedAuthorization, `Bearer ${TOKEN}`);
  assert.equal(observedServerlessAuthorization, null);
  assert.equal(observedUrl.includes(TOKEN), false);
});

test("enabled IAM auth gets a metadata ID token and preserves both auth layers", async () => {
  const audience = "https://private-api.example";
  const idToken = googleIdToken(audience);
  const calls: string[] = [];
  const client = new BackendClient(
    {
      baseUrl: audience,
      bearerToken: TOKEN,
      iamAuth: { enabled: true, audience: `${audience}/` },
    },
    async (input, init) => {
      const url = new URL(String(input));
      calls.push(url.href);
      const headers = new Headers(init?.headers);
      assert.equal(init?.redirect, "error");
      assert.equal(init?.cache, "no-store");

      if (url.hostname === "metadata.google.internal") {
        assert.equal(init?.method, "GET");
        assert.equal(headers.get("metadata-flavor"), "Google");
        assert.equal(headers.get("authorization"), null);
        assert.equal(headers.get("x-serverless-authorization"), null);
        assert.equal(url.searchParams.get("audience"), audience);
        assert.equal(url.searchParams.get("format"), null);
        return new Response(idToken, {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        });
      }

      assert.equal(url.href, `${audience}/health`);
      assert.equal(headers.get("authorization"), `Bearer ${TOKEN}`);
      assert.equal(
        headers.get("x-serverless-authorization"),
        `Bearer ${idToken}`,
      );
      assert.equal(url.href.includes(TOKEN), false);
      assert.equal(url.href.includes(idToken), false);
      return json({ status: "ok" });
    },
  );

  await client.get("/health");
  assert.equal(calls.length, 2);
  assert.equal(
    calls[0].startsWith(
      "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?",
    ),
    true,
  );
});

test("backend URL supports the private-origin fallback and rejects inconsistent dual configuration", () => {
  assert.equal(
    resolveBackendBaseUrl(
      undefined,
      "https://private-api.example/",
    ),
    "https://private-api.example",
  );
  assert.equal(
    resolveBackendBaseUrl(
      "https://private-api.example",
      "https://private-api.example/",
    ),
    "https://private-api.example",
  );
  assert.throws(
    () =>
      resolveBackendBaseUrl(
        "https://api-a.example",
        "https://api-b.example",
      ),
    (error: unknown) =>
      error instanceof BackendRequestError &&
      error.code === "backend_configuration_conflict",
  );
});

test("IAM auth configuration is explicit and pins the audience to the private origin", () => {
  assert.deepEqual(
    resolveBackendIamAuth(
      "false",
      undefined,
      "https://private-api.example",
    ),
    { enabled: false },
  );
  assert.deepEqual(
    resolveBackendIamAuth(
      "true",
      "https://private-api.example/",
      "https://private-api.example",
    ),
    {
      enabled: true,
      audience: "https://private-api.example",
    },
  );

  for (const resolve of [
    () =>
      resolveBackendIamAuth(
        undefined,
        undefined,
        "https://private-api.example",
      ),
    () =>
      resolveBackendIamAuth(
        "false",
        "https://private-api.example",
        "https://private-api.example",
      ),
    () =>
      resolveBackendIamAuth(
        "true",
        undefined,
        "https://private-api.example",
      ),
    () =>
      resolveBackendIamAuth(
        "true",
        "https://other-api.example",
        "https://private-api.example",
      ),
    () =>
      resolveBackendIamAuth(
        "true",
        "http://private-api.example",
        "https://private-api.example",
      ),
  ]) {
    assert.throws(resolve, BackendRequestError);
  }
});

test("IAM token acquisition fails closed without leaking metadata responses", async () => {
  const leakedValue = "metadata-response-must-not-leak";
  const client = new BackendClient(
    {
      baseUrl: "https://private-api.example",
      bearerToken: TOKEN,
      iamAuth: {
        enabled: true,
        audience: "https://private-api.example",
      },
    },
    async (input) => {
      const url = new URL(String(input));
      assert.equal(url.hostname, "metadata.google.internal");
      return new Response(leakedValue, { status: 500 });
    },
  );

  await assert.rejects(
    client.get("/health"),
    (error: unknown) =>
      error instanceof BackendRequestError &&
      error.code === "backend_iam_token_unavailable" &&
      !error.message.includes(leakedValue) &&
      !error.message.includes(TOKEN),
  );
});

test("IAM token acquisition rejects wrong-audience and oversized tokens", async () => {
  assert.ok(BACKEND_IAM_TOKEN_TIMEOUT_MS < BACKEND_DEFAULT_TIMEOUT_MS);
  const audience = "https://private-api.example";

  for (const metadataResponse of [
    new Response(googleIdToken("https://wrong-api.example")),
    new Response("oversized", {
      headers: { "Content-Length": "20000" },
    }),
  ]) {
    const client = new BackendClient(
      {
        baseUrl: audience,
        bearerToken: TOKEN,
        iamAuth: { enabled: true, audience },
      },
      async () => metadataResponse.clone(),
    );
    await assert.rejects(
      client.get("/health"),
      (error: unknown) =>
        error instanceof BackendRequestError &&
        error.code === "backend_iam_token_unavailable",
    );
  }
});

test("backend client enforces finite request timeout bounds", async () => {
  assert.ok(BACKEND_PAY_TIMEOUT_MS > BACKEND_DEFAULT_TIMEOUT_MS);
  assert.ok(BACKEND_FULFILL_TIMEOUT_MS > BACKEND_DEFAULT_TIMEOUT_MS);
  assert.ok(BACKEND_PAY_TIMEOUT_MS <= BACKEND_MAX_TIMEOUT_MS);
  assert.ok(BACKEND_FULFILL_TIMEOUT_MS <= BACKEND_MAX_TIMEOUT_MS);

  assert.throws(
    () =>
      new BackendClient({
        baseUrl: "https://private-api.example",
        bearerToken: TOKEN,
        iamAuth: { enabled: false },
        timeoutMs: Number.POSITIVE_INFINITY,
      }),
    (error: unknown) =>
      error instanceof BackendRequestError &&
      error.code === "backend_timeout_invalid",
  );

  const client = new BackendClient(
    {
      baseUrl: "https://private-api.example",
      bearerToken: TOKEN,
      iamAuth: { enabled: false },
    },
    async (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          },
          { once: true },
        );
      }),
  );
  await assert.rejects(
    client.get("/health", { timeoutMs: 5 }),
    (error: unknown) =>
      error instanceof BackendRequestError &&
      error.code === "backend_timeout",
  );
  await assert.rejects(
    client.get("/health", {
      timeoutMs: BACKEND_MAX_TIMEOUT_MS + 1,
    }),
    (error: unknown) =>
      error instanceof BackendRequestError &&
      error.code === "backend_timeout_invalid",
  );
});

test("health without explicit movesFunds fails closed", async () => {
  const client = new BackendClient(
    {
      baseUrl: "https://private-api.example",
      bearerToken: TOKEN,
      iamAuth: { enabled: false },
    },
    async () =>
      json({
        status: "ok",
        service: "autonomerce-api",
        paymentMode: "mock",
      }),
  );
  const status = await new AutonomerceService(client, false).status();
  assert.equal(status.connected, false);
  assert.match(status.reason ?? "", /movesFunds/);
});

test("same-origin JSON guard rejects cross-origin mutations", async () => {
  const request = new Request("https://web.example/api/autonomerce/onboarding", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "https://attacker.example",
      "sec-fetch-site": "cross-site",
    },
    body: "{}",
  });
  await assert.rejects(readProtectedJson(request), /Cross-origin/);
});

test("same-origin JSON guard accepts the browser Host origin when the framework canonicalizes request.url", async () => {
  const request = new Request(
    "http://localhost:3210/api/autonomerce/auth/login",
    {
      method: "POST",
      headers: {
        host: "127.0.0.1:3210",
        "content-type": "application/json",
        origin: "http://127.0.0.1:3210",
        "sec-fetch-site": "same-origin",
      },
      body: "{}",
    },
  );
  assert.deepEqual(await readProtectedJson(request), {});
});

test("mocked backend workflow returns backend receipt and metrics IDs", async () => {
  const calls: string[] = [];
  const endpointTimeouts = new Map<string, number | undefined>();
  let receiptPublished = false;
  let fulfillmentCompleted = false;
  let prospectRequest: Record<string, unknown> | null = null;
  class RecordingBackendClient extends BackendClient {
    override post<T>(
      path: string,
      body?: unknown,
      options?: BackendRequestOptions,
    ): Promise<T> {
      endpointTimeouts.set(path, options?.timeoutMs);
      return super.post<T>(path, body, options);
    }
  }
  const client = new RecordingBackendClient(
    {
      baseUrl: "https://private-api.example",
      bearerToken: TOKEN,
      iamAuth: { enabled: false },
    },
    async (input, init) => {
      const url = new URL(String(input));
      calls.push(`${init?.method ?? "GET"} ${url.pathname}`);
      const requestBody = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : null;
      assert.equal(
        new Headers(init?.headers).get("authorization"),
        `Bearer ${TOKEN}`,
      );
      if (url.pathname === "/health") {
        return json({
          status: "ok",
          service: "autonomerce-api",
          storage: "memory",
          paymentMode: "mock",
          movesFunds: false,
          integrations: { payment: "mock" },
        });
      }
      if (url.pathname === "/prospects") {
        prospectRequest = requestBody;
        return json({
          needId: "need_backend_001",
          buyerAgentUrl: "https://buyer.example/agent",
          desiredOutcome: "Verify a claim",
          maximumPriceUsdc: "2",
        }, 201);
      }
      if (url.pathname === "/proposals") {
        if ((init?.method ?? "GET") === "GET") {
          return json({
            proposals: fulfillmentCompleted
              ? [
                  {
                    proposalId: "proposal_backend_001",
                    skuId: "sku_backend_001",
                    offeredOutcome: "Verified result",
                    priceUsdc: "0.9",
                    deliverySeconds: 100,
                    state: "failed",
                    revision: 2,
                  },
                ]
              : [],
            count: fulfillmentCompleted ? 1 : 0,
          });
        }
        return json({
          proposalId: "proposal_backend_001",
          skuId: "sku_backend_001",
          offeredOutcome: "Verified result",
          priceUsdc: "1",
          deliverySeconds: 120,
          state: "offered",
          revision: 1,
        }, 201);
      }
      if (url.pathname.endsWith("/counter")) {
        return json({
          accepted: true,
          proposal: {
            proposalId: "proposal_backend_001",
            skuId: "sku_backend_001",
            offeredOutcome: "Verified result",
            priceUsdc: "0.9",
            deliverySeconds: 100,
            state: "countered",
            revision: 2,
          },
        });
      }
      if (url.pathname.endsWith("/accept")) {
        return json({
          accepted: true,
          proposal: {
            proposalId: "proposal_backend_001",
            skuId: "sku_backend_001",
            offeredOutcome: "Verified result",
            priceUsdc: "0.9",
            deliverySeconds: 100,
            state: "accepted",
            revision: 2,
          },
        });
      }
      if (url.pathname.endsWith("/pay")) {
        return json({
          paymentId: "payment_backend_001",
          proposalId: "proposal_backend_001",
          state: "confirmed",
          amountUsdc: "0.9",
          chain: "ARC-TESTNET",
          transactionHash: "0xbackend",
          explorerUrl: null,
          confirmedAt: "2026-07-31T10:00:00Z",
          mocked: true,
        });
      }
      if (url.pathname.endsWith("/fulfill")) {
        fulfillmentCompleted = true;
        return json({
          fulfillmentId: "fulfillment_backend_001",
          proposalId: "proposal_backend_001",
          paymentId: "payment_backend_001",
          artifactHash: "sha256:backend",
          accepted: false,
          validator: "mock-validator",
          acceptanceResults: { non_empty_artifact: false },
          deliveredAt: "2026-07-31T10:00:01Z",
        });
      }
      if (url.pathname.endsWith("/publish")) {
        assert.deepEqual(requestBody, {
          consentReference: "publication:test:001",
          fields: [
            "payment",
            "fulfillment",
            "acceptanceVerdict",
          ],
        });
        receiptPublished = true;
        return json({
          published: true,
          receiptId: "receipt_backend_001",
          proposalId: "proposal_backend_001",
          publishedAt: "2026-07-31T10:00:02Z",
          version: 1,
          fields: [
            "payment",
            "fulfillment",
            "acceptanceVerdict",
          ],
          fulfillmentAvailable: true,
        });
      }
      if (url.pathname.startsWith("/receipts/")) {
        assert.equal(
          receiptPublished,
          true,
          "receipt GET must follow authenticated publication",
        );
        return json({
          receiptId: "receipt_backend_001",
          proposalId: "proposal_backend_001",
          anonymizedOrderId: "order_backend_001",
          acceptanceVerdict: "rejected",
        });
      }
      if (url.pathname === "/metrics") {
        return json({
          metricsId: "metrics_backend_001",
          registeredSellerAgents: 1,
          activatedSellerAgents: 1,
          proposalsSent: 1,
          proposalAcceptanceRate: "1",
          negotiatedPriceChangeUsdc: "0.1",
          paidTasks: null,
          paidTasksStatus: "requires_external_customer_classification",
          confirmedLivePayments: 0,
          mockedPaymentCount: 1,
          successfulFulfillment: 0,
          usdcRevenue: null,
          liveSettlementVolumeUsdc: "0",
          mockedPaymentVolumeUsdc: "0.9",
          medianDeliverySeconds: 1,
          paymentFailures: 0,
          policyDenials: 0,
          duplicatePaymentCount: 0,
          grossMarginUsdc: null,
          grossMarginStatus: "requires_measured_variable_costs",
          revenueClassification: "unmeasured_external_customer_status",
        });
      }
      return json({ detail: "not found" }, 404);
    },
  );

  const result = await new AutonomerceService(client, false).runWorkflow({
    onboarding: {
      sellerId: "seller_backend_001",
      skuId: "sku_backend_001",
      policyId: "policy_backend_001",
    },
    ownerWorkflowOperationId: "00000000-0000-4000-8000-000000000001",
    operationExpiresAt: new Date(
      Date.now() + 60 * 60 * 1_000,
    ).toISOString(),
    buyerAgentUrl: "https://buyer.example/agent",
    buyerOptInConfirmed: true,
    consentReference: "consent:test:001",
    publicationAuthorized: true,
    publicationConsentReference: "publication:test:001",
    desiredOutcome: "Verify a claim",
    maximumPriceUsdc: "2",
    problemObserved: "Claim needs checking",
    offerPriceUsdc: "1",
    counterPriceUsdc: "0.9",
    deliverySeconds: 100,
  });

  assert.equal(result.receipt.receiptId, "receipt_backend_001");
  assert.equal(result.metrics.metricsId, "metrics_backend_001");
  assert.equal(result.payment.paymentId, "payment_backend_001");
  assert.equal(result.proposal.state, "failed");
  assert.equal(result.fulfillment.accepted, false);
  assert.equal(result.timeline.at(-1)?.state, "failed");
  assert.equal(result.backend.movesFunds, false);
  assert.deepEqual(prospectRequest, {
    buyerAgentUrl: "https://buyer.example/agent",
    desiredOutcome: "Verify a claim",
    maximumPriceUsdc: "2",
    requiredTags: [],
    inputPayload: {
      claim: "Verify a claim",
      source: "https://buyer.example/agent",
      problemObserved: "Claim needs checking",
    },
    optedIn: true,
    consentReference: "consent:test:001",
  });
  assert.ok(calls.includes("POST /proposals/proposal_backend_001/pay"));
  assert.equal(
    endpointTimeouts.get("/proposals/proposal_backend_001/pay"),
    BACKEND_PAY_TIMEOUT_MS,
  );
  assert.equal(
    endpointTimeouts.get("/proposals/proposal_backend_001/fulfill"),
    BACKEND_FULFILL_TIMEOUT_MS,
  );
  const fulfillIndex = calls.indexOf(
    "POST /proposals/proposal_backend_001/fulfill",
  );
  assert.ok(fulfillIndex >= 0);
  assert.ok(
    calls.lastIndexOf("GET /proposals") > fulfillIndex,
    "authoritative proposal refresh must follow fulfillment",
  );
  const publishIndex = calls.indexOf(
    "POST /receipts/proposal_backend_001/publish",
  );
  const getIndex = calls.indexOf(
    "GET /receipts/proposal_backend_001",
  );
  assert.ok(publishIndex >= 0);
  assert.ok(getIndex > publishIndex);
});

test("resumed workflow rejects changed immutable pricing inputs", async () => {
  const calls: string[] = [];
  const operationExpiresAt = new Date(
    Date.now() + 60 * 60 * 1_000,
  ).toISOString();
  const baseInput = {
    onboarding: {
      sellerId: "seller_backend_001",
      skuId: "sku_backend_001",
      policyId: "policy_backend_001",
    },
    ownerWorkflowOperationId:
      "00000000-0000-4000-8000-000000000009",
    operationExpiresAt,
    buyerAgentUrl: "https://buyer.example/agent",
    buyerOptInConfirmed: true,
    consentReference: "consent:test:changed-input",
    publicationAuthorized: false,
    publicationConsentReference: null,
    desiredOutcome: "Verify a claim",
    maximumPriceUsdc: "2",
    problemObserved: "Claim needs checking",
    deliverySeconds: 100,
  };
  const originalInput = {
    ...baseInput,
    offerPriceUsdc: "1",
    counterPriceUsdc: "0.9",
  };
  const changedInput = {
    ...baseInput,
    offerPriceUsdc: "0.9",
    counterPriceUsdc: "0.8",
  };
  const originalProblem = [
    originalInput.problemObserved,
    "",
    `Owner workflow operation: ${originalInput.ownerWorkflowOperationId}`,
    `Owner workflow fingerprint: ${workflowOperationFingerprint(originalInput)}`,
  ].join("\n");

  const client = new BackendClient(
    {
      baseUrl: "https://private-api.example",
      bearerToken: TOKEN,
      iamAuth: { enabled: false },
    },
    async (input, init) => {
      const url = new URL(String(input));
      calls.push(`${init?.method ?? "GET"} ${url.pathname}`);
      if (url.pathname === "/health") {
        return json({
          status: "ok",
          service: "autonomerce-api",
          storage: "sqlite",
          paymentMode: "testnet",
          movesFunds: true,
          integrations: { payment: "circle" },
        });
      }
      if (url.pathname === "/prospects") {
        return json({
          needId: "need_backend_changed",
          buyerAgentUrl: changedInput.buyerAgentUrl,
          desiredOutcome: changedInput.desiredOutcome,
          maximumPriceUsdc: changedInput.maximumPriceUsdc,
        }, 201);
      }
      if (url.pathname === "/proposals") {
        return json({
          proposals: [
            {
              proposalId: "proposal_backend_changed",
              buyerNeedId: "need_backend_changed",
              buyerAgentUrl: changedInput.buyerAgentUrl,
              skuId: changedInput.onboarding.skuId,
              problemObserved: originalProblem,
              offeredOutcome: changedInput.desiredOutcome,
              priceUsdc: "0.9",
              deliverySeconds: changedInput.deliverySeconds,
              expiresAt: changedInput.operationExpiresAt,
              state: "countered",
              revision: 2,
            },
          ],
          count: 1,
        });
      }
      return json({ detail: "unexpected request" }, 500);
    },
  );

  await assert.rejects(
    new AutonomerceService(client, true).runWorkflow(changedInput),
    (error: unknown) =>
      error instanceof BackendRequestError &&
      error.code === "workflow_operation_conflict" &&
      error.status === 409,
  );
  assert.equal(
    calls.some((call) => call.endsWith("/pay")),
    false,
  );
});

test("resumed workflow rejects a changed seller before creating or paying", async () => {
  const calls: string[] = [];
  const operationExpiresAt = new Date(
    Date.now() + 60 * 60 * 1_000,
  ).toISOString();
  const originalInput = {
    onboarding: {
      sellerId: "seller_backend_original",
      skuId: "sku_backend_001",
      policyId: "policy_backend_001",
    },
    ownerWorkflowOperationId:
      "00000000-0000-4000-8000-000000000010",
    operationExpiresAt,
    buyerAgentUrl: "https://buyer.example/agent",
    buyerOptInConfirmed: true,
    consentReference: "consent:test:changed-seller",
    publicationAuthorized: false,
    publicationConsentReference: null,
    desiredOutcome: "Verify a claim",
    maximumPriceUsdc: "2",
    problemObserved: "Claim needs checking",
    offerPriceUsdc: "1",
    counterPriceUsdc: "0.9",
    deliverySeconds: 100,
  };
  const changedInput = {
    ...originalInput,
    onboarding: {
      ...originalInput.onboarding,
      sellerId: "seller_backend_changed",
    },
  };
  const originalProblem = [
    originalInput.problemObserved,
    "",
    `Owner workflow operation: ${originalInput.ownerWorkflowOperationId}`,
    `Owner workflow fingerprint: ${workflowOperationFingerprint(originalInput)}`,
  ].join("\n");

  const client = new BackendClient(
    {
      baseUrl: "https://private-api.example",
      bearerToken: TOKEN,
      iamAuth: { enabled: false },
    },
    async (input, init) => {
      const url = new URL(String(input));
      calls.push(
        `${init?.method ?? "GET"} ${url.pathname}${url.search}`,
      );
      if (url.pathname === "/health") {
        return json({
          status: "ok",
          service: "autonomerce-api",
          storage: "sqlite",
          paymentMode: "testnet",
          movesFunds: true,
          integrations: { payment: "circle" },
        });
      }
      if (url.pathname === "/prospects") {
        return json({
          needId: "need_backend_changed_seller",
          buyerAgentUrl: changedInput.buyerAgentUrl,
          desiredOutcome: changedInput.desiredOutcome,
          maximumPriceUsdc: changedInput.maximumPriceUsdc,
        }, 201);
      }
      if (url.pathname === "/proposals") {
        assert.equal(
          url.searchParams.has("sellerId"),
          false,
          "operation replay lookup must cover every proposal owned by the tenant",
        );
        return json({
          proposals: [
            {
              proposalId: "proposal_backend_original_seller",
              buyerNeedId: "need_backend_changed_seller",
              buyerAgentUrl: changedInput.buyerAgentUrl,
              skuId: originalInput.onboarding.skuId,
              problemObserved: originalProblem,
              offeredOutcome: changedInput.desiredOutcome,
              priceUsdc: "0.9",
              deliverySeconds: changedInput.deliverySeconds,
              expiresAt: changedInput.operationExpiresAt,
              state: "delivered",
              revision: 4,
            },
          ],
          count: 1,
        });
      }
      return json({ detail: "unexpected request" }, 500);
    },
  );

  await assert.rejects(
    new AutonomerceService(client, true).runWorkflow(changedInput),
    (error: unknown) =>
      error instanceof BackendRequestError &&
      error.code === "workflow_operation_conflict" &&
      error.status === 409,
  );
  assert.equal(
    calls.some((call) => call.startsWith("POST /proposals")),
    false,
  );
  assert.equal(
    calls.some((call) => call.includes("/pay")),
    false,
  );
});
