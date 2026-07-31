import assert from "node:assert/strict";
import test from "node:test";

import {
  authenticateOwnerRequest,
  createOwnerSession,
  OWNER_SESSION_COOKIE,
  ownerAuthStatus,
  OwnerAuthenticationError,
  requireOwnerSessionWithConfig,
  resolveOwnerAuthConfig,
  serializeExpiredOwnerSessionCookie,
  serializeOwnerSessionCookie,
  validateOwnerLogoutRequest,
  verifyOwnerSession,
  type OwnerAuthConfig,
} from "../lib/owner-session-core";

const NOW = Date.UTC(2026, 6, 31, 12, 0, 0);
const OWNER_TOKEN = "owner-token-for-web-only-32-bytes-minimum";
const API_BEARER = "private-api-bearer-only";
const SESSION_SECRET =
  "session-secret-with-at-least-thirty-two-characters";
const CONFIG: OwnerAuthConfig = {
  ownerToken: OWNER_TOKEN,
  sessionSecret: SESSION_SECRET,
};

function sameOriginRequest(
  path: string,
  body: unknown,
  cookie?: string,
): Request {
  return new Request(`https://web.example${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "https://web.example",
      "sec-fetch-site": "same-origin",
      ...(cookie ? { cookie } : {}),
    },
    body: JSON.stringify(body),
  });
}

test("protected mutation authentication rejects a request without a session", () => {
  const request = sameOriginRequest(
    "/api/autonomerce/onboarding",
    {},
  );
  assert.throws(
    () => requireOwnerSessionWithConfig(request, CONFIG, NOW),
    (error: unknown) =>
      error instanceof OwnerAuthenticationError &&
      error.status === 401 &&
      error.code === "owner_session_required",
  );
});

test("owner login issues a signed short-lived strict HttpOnly cookie and status accepts it", async () => {
  const login = await authenticateOwnerRequest(
    sameOriginRequest(
      "/api/autonomerce/auth/login",
      { ownerToken: OWNER_TOKEN },
    ),
    CONFIG,
    NOW,
  );
  const setCookie = serializeOwnerSessionCookie(
    login.cookieValue,
    login.expiresAt,
    true,
  );

  assert.equal(login.status.authenticated, true);
  assert.match(setCookie, /HttpOnly/);
  assert.match(setCookie, /SameSite=Strict/);
  assert.match(setCookie, /Max-Age=900/);
  assert.match(setCookie, /Secure/);
  assert.equal(setCookie.includes(OWNER_TOKEN), false);
  assert.equal(setCookie.includes(API_BEARER), false);
  assert.equal(setCookie.includes(SESSION_SECRET), false);

  const authenticatedRequest = new Request(
    "https://web.example/api/autonomerce/auth/status",
    {
      headers: {
        cookie: `${OWNER_SESSION_COOKIE}=${encodeURIComponent(
          login.cookieValue,
        )}`,
      },
    },
  );
  const status = ownerAuthStatus(authenticatedRequest, CONFIG, NOW);
  assert.equal(status.authenticated, true);
  assert.equal(status.expiresAt, login.expiresAt);
  assert.doesNotThrow(() =>
    requireOwnerSessionWithConfig(
      authenticatedRequest,
      CONFIG,
      NOW,
    ),
  );
});

test("forged and expired session cookies are rejected", () => {
  const current = createOwnerSession(OWNER_TOKEN, CONFIG, NOW);
  const forged = `${current.cookieValue.slice(0, -1)}${
    current.cookieValue.endsWith("a") ? "b" : "a"
  }`;
  assert.equal(verifyOwnerSession(forged, CONFIG, NOW), null);

  const old = createOwnerSession(
    OWNER_TOKEN,
    CONFIG,
    NOW - 16 * 60 * 1_000,
  );
  assert.equal(verifyOwnerSession(old.cookieValue, CONFIG, NOW), null);
});

test("logout accepts only same-origin JSON and expires the owner cookie", async () => {
  await validateOwnerLogoutRequest(
    sameOriginRequest("/api/autonomerce/auth/logout", {}),
  );
  const setCookie = serializeExpiredOwnerSessionCookie(true);
  assert.match(setCookie, new RegExp(`^${OWNER_SESSION_COOKIE}=`));
  assert.match(setCookie, /HttpOnly/);
  assert.match(setCookie, /SameSite=Strict/);
  assert.match(setCookie, /Max-Age=0/);
  assert.match(setCookie, /Expires=Thu, 01 Jan 1970 00:00:00 GMT/);
});

test("owner, API bearer, and session-signing secrets remain isolated", async () => {
  const config = resolveOwnerAuthConfig({
    AUTONOMERCE_WEB_OWNER_TOKEN: OWNER_TOKEN,
    AUTONOMERCE_WEB_SESSION_SECRET: SESSION_SECRET,
    AUTONOMERCE_API_BEARER_TOKEN: API_BEARER,
  });

  await assert.rejects(
    authenticateOwnerRequest(
      sameOriginRequest(
        "/api/autonomerce/auth/login",
        { ownerToken: API_BEARER },
      ),
      config,
      NOW,
    ),
    (error: unknown) =>
      error instanceof OwnerAuthenticationError &&
      error.code === "owner_credentials_invalid",
  );

  assert.throws(
    () =>
      resolveOwnerAuthConfig({
        AUTONOMERCE_WEB_OWNER_TOKEN: API_BEARER,
        AUTONOMERCE_WEB_SESSION_SECRET: SESSION_SECRET,
        AUTONOMERCE_API_BEARER_TOKEN: API_BEARER,
      }),
    (error: unknown) =>
      error instanceof OwnerAuthenticationError &&
      error.code === "owner_auth_configuration_invalid",
  );

  assert.throws(
    () =>
      resolveOwnerAuthConfig({
        AUTONOMERCE_WEB_OWNER_TOKEN: "too-short-owner-token",
        AUTONOMERCE_WEB_SESSION_SECRET: SESSION_SECRET,
        AUTONOMERCE_API_BEARER_TOKEN: API_BEARER,
      }),
    (error: unknown) =>
      error instanceof OwnerAuthenticationError &&
      error.code === "owner_auth_configuration_invalid",
  );
});
