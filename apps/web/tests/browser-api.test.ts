import assert from "node:assert/strict";
import test from "node:test";

import {
  getBackendStatus,
  getOwnerAuthStatus,
  loginOwner,
  logoutOwner,
} from "../lib/browser-api";

test("browser client calls only the same-origin proxy and receives sanitized status", async () => {
  const originalFetch = globalThis.fetch;
  let observedPath = "";
  let observedAuthorization: string | null = "unexpected";
  globalThis.fetch = async (input, init) => {
    observedPath = String(input);
    observedAuthorization = new Headers(init?.headers).get("authorization");
    return new Response(
      JSON.stringify({
        connected: true,
        mode: "mock",
        movesFunds: false,
        mutationsAllowed: true,
        service: "autonomerce-api",
        storage: "memory",
        integrations: { payment: "mock" },
        reason: null,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const status = await getBackendStatus();
    assert.equal(observedPath, "/api/autonomerce/status");
    assert.equal(observedAuthorization, null);
    assert.equal(status.movesFunds, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("browser owner auth uses only same-origin JSON and never sends an API bearer", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{
    path: string;
    authorization: string | null;
    credentials: RequestCredentials | undefined;
    body: string | null;
  }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({
      path: String(input),
      authorization:
        new Headers(init?.headers).get("authorization"),
      credentials: init?.credentials,
      body: typeof init?.body === "string" ? init.body : null,
    });
    return new Response(
      JSON.stringify({
        configured: true,
        authenticated:
          String(input) === "/api/autonomerce/auth/login",
        expiresAt:
          String(input) === "/api/autonomerce/auth/login"
            ? "2026-07-31T12:15:00.000Z"
            : null,
        reason: null,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await getOwnerAuthStatus();
    await loginOwner("dedicated-owner-token");
    await logoutOwner();

    assert.deepEqual(
      calls.map((call) => call.path),
      [
        "/api/autonomerce/auth/status",
        "/api/autonomerce/auth/login",
        "/api/autonomerce/auth/logout",
      ],
    );
    assert.ok(
      calls.every(
        (call) =>
          call.authorization === null &&
          call.credentials === "same-origin",
      ),
    );
    assert.deepEqual(JSON.parse(calls[1].body ?? ""), {
      ownerToken: "dedicated-owner-token",
    });
    assert.deepEqual(JSON.parse(calls[2].body ?? ""), {});
  } finally {
    globalThis.fetch = originalFetch;
  }
});
