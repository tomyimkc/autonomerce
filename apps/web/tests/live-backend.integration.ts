import assert from "node:assert/strict";
import {
  spawn,
  type ChildProcessByStdio,
} from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import net from "node:net";
import path from "node:path";
import type { Readable } from "node:stream";
import test from "node:test";

const TEST_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(TEST_DIRECTORY, "..");
const PROJECT_ROOT = path.resolve(WEB_ROOT, "../..");
const NEXT_CLI = path.join(
  WEB_ROOT,
  "node_modules",
  "next",
  "dist",
  "bin",
  "next",
);

const API_BEARER_TOKEN = "integration-api-bearer-token";
const OWNER_TOKEN = "integration-web-owner-token-32-bytes-minimum";
const SESSION_SECRET =
  "integration-session-secret-with-at-least-32-characters";
const CONSENT_REFERENCE =
  "consent:live-web-integration:buyer.example:v1";

interface ManagedProcess {
  child: ChildProcessByStdio<null, Readable, Readable>;
  label: string;
  logs: string;
}

interface JsonResponse {
  response: Response;
  payload: unknown;
  text: string;
}

function appendLogs(service: ManagedProcess, chunk: Buffer): void {
  service.logs = `${service.logs}${chunk.toString("utf8")}`.slice(-30_000);
}

function startService(
  label: string,
  command: string,
  args: string[],
  options: {
    cwd: string;
    env: NodeJS.ProcessEnv;
  },
): ManagedProcess {
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: options.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const service: ManagedProcess = { child, label, logs: "" };
  child.stdout.on("data", (chunk: Buffer) => appendLogs(service, chunk));
  child.stderr.on("data", (chunk: Buffer) => appendLogs(service, chunk));
  return service;
}

async function stopService(service: ManagedProcess): Promise<void> {
  if (service.child.exitCode !== null || service.child.signalCode !== null) {
    return;
  }

  service.child.kill("SIGINT");
  const exitedAfterInterrupt = await Promise.race([
    once(service.child, "exit").then(() => true),
    new Promise<boolean>((resolve) =>
      setTimeout(() => resolve(false), 3_000),
    ),
  ]);
  if (
    exitedAfterInterrupt ||
    service.child.exitCode !== null ||
    service.child.signalCode !== null
  ) {
    return;
  }

  service.child.kill("SIGTERM");
  await Promise.race([
    once(service.child, "exit"),
    new Promise<void>((resolve) => setTimeout(resolve, 3_000)),
  ]);
}

async function freePort(): Promise<number> {
  const server = net.createServer();
  server.unref();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const port = address.port;
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
  return port;
}

async function waitForHttp(
  url: string,
  service: ManagedProcess,
  timeoutMs = 30_000,
): Promise<Response> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;

  while (Date.now() < deadline) {
    if (service.child.exitCode !== null) {
      throw new Error(
        `${service.label} exited with code ${service.child.exitCode}\n${service.logs}`,
      );
    }
    try {
      const response = await fetch(url, {
        cache: "no-store",
        redirect: "error",
      });
      if (response.ok) {
        return response;
      }
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }

  throw new Error(
    `${service.label} did not become ready: ${String(lastError)}\n${service.logs}`,
  );
}

async function jsonRequest(
  url: string,
  init?: RequestInit,
): Promise<JsonResponse> {
  const response = await fetch(url, {
    ...init,
    cache: "no-store",
    redirect: "error",
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(
        `${init?.method ?? "GET"} ${url} returned invalid JSON: ${text}`,
      );
    }
  }
  return { response, payload, text };
}

function objectValue(
  value: unknown,
  label: string,
): Record<string, unknown> {
  assert.ok(
    value && typeof value === "object" && !Array.isArray(value),
    `${label} must be an object`,
  );
  return value as Record<string, unknown>;
}

function cookiePair(response: Response): string {
  const setCookie = response.headers.get("set-cookie");
  assert.ok(setCookie, "owner login must issue a session cookie");
  return setCookie.split(";", 1)[0];
}

function webMutationHeaders(
  webOrigin: string,
  cookie?: string,
): HeadersInit {
  return {
    "Content-Type": "application/json",
    Origin: webOrigin,
    "Sec-Fetch-Site": "same-origin",
    ...(cookie ? { Cookie: cookie } : {}),
  };
}

async function findPython(): Promise<string> {
  const candidates = [
    process.env.AUTONOMERCE_INTEGRATION_PYTHON,
    path.join(PROJECT_ROOT, ".venv", "bin", "python"),
    "python3",
  ].filter((candidate): candidate is string => Boolean(candidate));

  for (const candidate of candidates) {
    const code = await new Promise<number | null>((resolve) => {
      const probe = spawn(
        candidate,
        ["-c", "import fastapi, uvicorn"],
        {
          cwd: PROJECT_ROOT,
          env: process.env,
          stdio: "ignore",
        },
      );
      probe.once("error", () => resolve(null));
      probe.once("exit", (exitCode) => resolve(exitCode));
    });
    if (code === 0) {
      return candidate;
    }
  }

  throw new Error(
    "No Python interpreter with FastAPI and uvicorn is available. Set AUTONOMERCE_INTEGRATION_PYTHON.",
  );
}

test(
  "LIVE web workflow completes against a running authenticated offline FastAPI backend",
  { timeout: 90_000 },
  async (t) => {
    const [apiPort, webPort, python] = await Promise.all([
      freePort(),
      freePort(),
      findPython(),
    ]);
    const apiOrigin = `http://127.0.0.1:${apiPort}`;
    const webOrigin = `http://127.0.0.1:${webPort}`;
    const pythonPath = [
      path.join(PROJECT_ROOT, "apps", "api"),
      path.join(PROJECT_ROOT, "packages"),
      process.env.PYTHONPATH,
    ]
      .filter(Boolean)
      .join(path.delimiter);

    const api = startService(
      "FastAPI backend",
      python,
      [
        "-m",
        "uvicorn",
        "autonomerce.api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        String(apiPort),
        "--log-level",
        "warning",
      ],
      {
        cwd: PROJECT_ROOT,
        env: {
          ...process.env,
          PYTHONPATH: pythonPath,
          PYTHONDONTWRITEBYTECODE: "1",
          AUTONOMERCE_DEPLOYMENT_MODE: "local-offline",
          AUTONOMERCE_MODE: "offline",
          AUTONOMERCE_PRODUCTIZER_MODE: "offline",
          AUTONOMERCE_PAYMENT_MODE: "offline",
          AUTONOMERCE_PAYMENT_STORE_DURABILITY: "memory-offline",
          AUTONOMERCE_COMMERCE_SQLITE_PATH: "",
          AUTONOMERCE_TRUSTED_HOSTS: "127.0.0.1,localhost",
          AUTONOMERCE_API_BEARER_TOKEN: API_BEARER_TOKEN,
          AUTONOMERCE_API_OWNER_ID: "live-web-integration-owner",
          GEMINI_API_KEY: "",
          GOOGLE_API_KEY: "",
          CIRCLE_API_KEY: "",
        },
      },
    );
    t.after(async () => stopService(api));

    const apiHealthResponse = await waitForHttp(
      `${apiOrigin}/health`,
      api,
    );
    const apiHealth = objectValue(
      await apiHealthResponse.json(),
      "backend health",
    );
    assert.equal(apiHealth.status, "ok");
    assert.equal(apiHealth.paymentMode, "offline");
    assert.equal(apiHealth.movesFunds, false);
    assert.equal(apiHealth.authenticationRequired, true);

    const web = startService(
      "Next.js web server",
      process.execPath,
      [
        NEXT_CLI,
        "dev",
        "--hostname",
        "127.0.0.1",
        "--port",
        String(webPort),
      ],
      {
        cwd: WEB_ROOT,
        env: {
          ...process.env,
          NEXT_TELEMETRY_DISABLED: "1",
          AUTONOMERCE_API_BASE_URL: "",
          AUTONOMERCE_API_PRIVATE_ORIGIN: apiOrigin,
          AUTONOMERCE_API_BEARER_TOKEN: API_BEARER_TOKEN,
          AUTONOMERCE_WEB_OWNER_TOKEN: OWNER_TOKEN,
          AUTONOMERCE_WEB_SESSION_SECRET: SESSION_SECRET,
          AUTONOMERCE_WEB_TRUST_PROXY_HEADERS: "false",
          AUTONOMERCE_ALLOW_MOVES_FUNDS: "false",
        },
      },
    );
    t.after(async () => stopService(web));
    await waitForHttp(
      `${webOrigin}/api/autonomerce/auth/status`,
      web,
    );

    const unauthenticated = await jsonRequest(
      `${webOrigin}/api/autonomerce/onboarding`,
      {
        method: "POST",
        headers: webMutationHeaders(webOrigin),
        body: "{}",
      },
    );
    assert.equal(unauthenticated.response.status, 401);
    assert.equal(
      objectValue(
        objectValue(unauthenticated.payload, "unauthenticated response")
          .error,
        "unauthenticated error",
      ).code,
      "owner_session_required",
    );

    const login = await jsonRequest(
      `${webOrigin}/api/autonomerce/auth/login`,
      {
        method: "POST",
        headers: webMutationHeaders(webOrigin),
        body: JSON.stringify({ ownerToken: OWNER_TOKEN }),
      },
    );
    assert.equal(login.response.status, 200, login.text);
    const loginStatus = objectValue(login.payload, "login response");
    assert.equal(loginStatus.authenticated, true);
    const sessionCookie = cookiePair(login.response);
    const rawSetCookie = login.response.headers.get("set-cookie") ?? "";
    assert.match(rawSetCookie, /HttpOnly/i);
    assert.match(rawSetCookie, /SameSite=Strict/i);
    assert.equal(rawSetCookie.includes(OWNER_TOKEN), false);
    assert.equal(rawSetCookie.includes(API_BEARER_TOKEN), false);
    assert.equal(rawSetCookie.includes(SESSION_SECRET), false);

    const authenticatedStatus = await jsonRequest(
      `${webOrigin}/api/autonomerce/auth/status`,
      { headers: { Cookie: sessionCookie } },
    );
    assert.equal(authenticatedStatus.response.status, 200);
    assert.equal(
      objectValue(
        authenticatedStatus.payload,
        "authenticated owner status",
      ).authenticated,
      true,
    );

    const onboardingInput = {
      agentName: "LIVE integration seller",
      agentUrl:
        "https://seller.example/.well-known/agent-card.json",
      protocol: "A2A",
      capabilityName: "Source verification",
      outcome: "Return a bounded verification result",
      priceUsdc: "1",
      deliverySeconds: 120,
      capacityPerHour: 20,
      minimumPriceUsdc: "0.8",
      maximumDiscountPercent: 20,
      maximumTasksPerHour: 20,
      allowedBuyerHost: "buyer.example",
      unattended: true,
    };
    const onboarding = await jsonRequest(
      `${webOrigin}/api/autonomerce/onboarding`,
      {
        method: "POST",
        headers: webMutationHeaders(webOrigin, sessionCookie),
        body: JSON.stringify(onboardingInput),
      },
    );
    assert.equal(onboarding.response.status, 201, onboarding.text);
    const onboardingResult = objectValue(
      onboarding.payload,
      "onboarding response",
    );
    for (const id of ["sellerId", "capabilityId", "skuId", "policyId"]) {
      assert.equal(typeof onboardingResult[id], "string", `${id} is required`);
    }

    const workflowInput = {
      onboarding: {
        sellerId: onboardingResult.sellerId,
        skuId: onboardingResult.skuId,
        policyId: onboardingResult.policyId,
      },
      ownerWorkflowOperationId: "00000000-0000-4000-8000-000000000001",
      operationExpiresAt: new Date(
        Date.now() + 60 * 60 * 1_000,
      ).toISOString(),
      buyerAgentUrl:
        "https://buyer.example/.well-known/agent-card.json",
      buyerOptInConfirmed: true,
      consentReference: CONSENT_REFERENCE,
      publicationAuthorized: true,
      publicationConsentReference:
        "publication:live-web-integration:buyer.example:v1",
      desiredOutcome: "Verify one supplied claim",
      maximumPriceUsdc: "2",
      problemObserved: "A claim needs source verification",
      offerPriceUsdc: "1",
      counterPriceUsdc: "0.9",
      deliverySeconds: 120,
    };
    const workflow = await jsonRequest(
      `${webOrigin}/api/autonomerce/workflow`,
      {
        method: "POST",
        headers: webMutationHeaders(webOrigin, sessionCookie),
        body: JSON.stringify(workflowInput),
      },
    );
    if (workflow.response.status !== 201) {
      const [diagnosticProposals, diagnosticMetrics] =
        await Promise.all([
          jsonRequest(`${apiOrigin}/proposals`, {
            headers: {
              Authorization: `Bearer ${API_BEARER_TOKEN}`,
            },
          }),
          jsonRequest(`${apiOrigin}/metrics`, {
            headers: {
              Authorization: `Bearer ${API_BEARER_TOKEN}`,
            },
          }),
        ]);
      assert.fail(
        [
          `workflow returned ${workflow.response.status}: ${workflow.text}`,
          `backend proposals: ${diagnosticProposals.text}`,
          `backend metrics: ${diagnosticMetrics.text}`,
          `web logs: ${web.logs}`,
          `api logs: ${api.logs}`,
        ].join("\n"),
      );
    }
    const result = objectValue(workflow.payload, "workflow response");
    const backend = objectValue(result.backend, "workflow backend");
    const prospect = objectValue(result.prospect, "workflow prospect");
    const proposal = objectValue(result.proposal, "workflow proposal");
    const payment = objectValue(result.payment, "workflow payment");
    const fulfillment = objectValue(
      result.fulfillment,
      "workflow fulfillment",
    );
    const receipt = objectValue(result.receipt, "workflow receipt");
    const metrics = objectValue(result.metrics, "workflow metrics");

    assert.equal(backend.connected, true);
    assert.equal(backend.mode, "offline");
    assert.equal(backend.movesFunds, false);
    assert.match(String(prospect.needId), /^need_/);
    assert.match(String(proposal.proposalId), /^proposal_/);
    assert.equal(proposal.state, "delivered");
    assert.match(String(payment.paymentId), /^payment_/);
    assert.equal(payment.state, "confirmed");
    assert.equal(payment.mocked, true);
    assert.match(String(fulfillment.fulfillmentId), /^fulfillment_/);
    assert.equal(fulfillment.accepted, true);
    assert.match(String(receipt.receiptId), /^receipt_/);
    assert.equal(receipt.proposalId, proposal.proposalId);
    assert.equal(receipt.acceptanceVerdict, "accepted");
    assert.equal(metrics.registeredSellerAgents, 1);
    assert.equal(metrics.activatedSellerAgents, 1);
    assert.equal(metrics.proposalsSent, 1);
    assert.equal(metrics.mockedPaymentCount, 1);
    assert.equal(metrics.successfulFulfillment, 1);

    const resumedWorkflow = await jsonRequest(
      `${webOrigin}/api/autonomerce/workflow`,
      {
        method: "POST",
        headers: webMutationHeaders(webOrigin, sessionCookie),
        body: JSON.stringify(workflowInput),
      },
    );
    assert.equal(
      resumedWorkflow.response.status,
      201,
      resumedWorkflow.text,
    );
    const resumedResult = objectValue(
      resumedWorkflow.payload,
      "resumed workflow response",
    );
    const resumedOperation = objectValue(
      resumedResult.operation,
      "resumed operation",
    );
    const resumedPayment = objectValue(
      resumedResult.payment,
      "resumed payment",
    );
    const resumedProposal = objectValue(
      resumedResult.proposal,
      "resumed proposal",
    );
    const resumedFulfillment = objectValue(
      resumedResult.fulfillment,
      "resumed fulfillment",
    );
    const resumedReceipt = objectValue(
      resumedResult.receipt,
      "resumed receipt",
    );
    const resumedMetrics = objectValue(
      resumedResult.metrics,
      "resumed metrics",
    );
    assert.equal(resumedOperation.resumed, true);
    assert.equal(resumedProposal.state, "delivered");
    assert.equal(resumedPayment.paymentId, payment.paymentId);
    assert.equal(
      resumedFulfillment.fulfillmentId,
      fulfillment.fulfillmentId,
    );
    assert.equal(resumedReceipt.receiptId, receipt.receiptId);
    assert.equal(resumedMetrics.mockedPaymentCount, 1);
    assert.equal(resumedMetrics.duplicatePaymentCount, 0);

    const prospects = await jsonRequest(`${apiOrigin}/prospects`, {
      headers: { Authorization: `Bearer ${API_BEARER_TOKEN}` },
    });
    assert.equal(prospects.response.status, 200, prospects.text);
    const prospectList = objectValue(
      prospects.payload,
      "backend prospects",
    ).prospects;
    assert.ok(Array.isArray(prospectList));
    assert.equal(prospectList.length, 1);
    assert.equal(
      objectValue(prospectList[0], "persisted prospect")
        .consentReference,
      CONSENT_REFERENCE,
    );

    const publicReceipt = await jsonRequest(
      `${apiOrigin}/receipts/${encodeURIComponent(
        String(proposal.proposalId),
      )}`,
    );
    assert.equal(publicReceipt.response.status, 200, publicReceipt.text);
    const publicReceiptPayload = objectValue(
      publicReceipt.payload,
      "public receipt",
    );
    assert.equal(publicReceiptPayload.receiptId, receipt.receiptId);
    assert.equal(publicReceiptPayload.proposalId, proposal.proposalId);
    assert.equal(publicReceiptPayload.acceptanceVerdict, "accepted");

    const unauthenticatedMetrics = await jsonRequest(
      `${apiOrigin}/metrics`,
    );
    assert.equal(unauthenticatedMetrics.response.status, 401);
    const authenticatedMetrics = await jsonRequest(
      `${apiOrigin}/metrics`,
      {
        headers: { Authorization: `Bearer ${API_BEARER_TOKEN}` },
      },
    );
    assert.equal(authenticatedMetrics.response.status, 200);
    assert.equal(
      objectValue(
        authenticatedMetrics.payload,
        "authenticated metrics",
      ).mockedPaymentCount,
      1,
    );

    const logout = await jsonRequest(
      `${webOrigin}/api/autonomerce/auth/logout`,
      {
        method: "POST",
        headers: webMutationHeaders(webOrigin, sessionCookie),
        body: "{}",
      },
    );
    assert.equal(logout.response.status, 200, logout.text);
    assert.match(
      logout.response.headers.get("set-cookie") ?? "",
      /Max-Age=0/i,
    );

    const failedLogin = await jsonRequest(
      `${webOrigin}/api/autonomerce/auth/login`,
      {
        method: "POST",
        headers: {
          ...webMutationHeaders(webOrigin),
          "X-Forwarded-For": "203.0.113.100",
        },
        body: JSON.stringify({
          ownerToken: "wrong-owner-token-with-at-least-32-characters",
        }),
      },
    );
    assert.equal(failedLogin.response.status, 401, failedLogin.text);

    const rotatedSpoof = await jsonRequest(
      `${webOrigin}/api/autonomerce/auth/login`,
      {
        method: "POST",
        headers: {
          ...webMutationHeaders(webOrigin),
          "X-Forwarded-For": "203.0.113.101",
        },
        body: JSON.stringify({
          ownerToken: "wrong-owner-token-with-at-least-32-characters",
        }),
      },
    );
    assert.equal(rotatedSpoof.response.status, 429, rotatedSpoof.text);
    assert.equal(
      objectValue(
        objectValue(rotatedSpoof.payload, "rotated spoof response")
          .error,
        "rotated spoof error",
      ).code,
      "owner_login_rate_limited",
    );
  },
);
