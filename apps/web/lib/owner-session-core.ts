import {
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";

import type { OwnerAuthStatus } from "./api-types";
import { parseOwnerLoginInput } from "./input-validation";
import { readProtectedJson } from "./request-guards";

export const OWNER_SESSION_COOKIE = "autonomerce_owner_session";
export const OWNER_SESSION_TTL_SECONDS = 15 * 60;

const SESSION_VERSION = 1;
const MAX_CLOCK_SKEW_SECONDS = 30;

export interface OwnerAuthConfig {
  ownerToken: string;
  sessionSecret: string;
  ttlSeconds?: number;
}

interface OwnerSessionPayload {
  v: number;
  iat: number;
  exp: number;
  nonce: string;
}

export class OwnerAuthenticationError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "OwnerAuthenticationError";
  }
}

function configurationError(message: string): never {
  throw new OwnerAuthenticationError(
    message,
    503,
    "owner_auth_configuration_invalid",
  );
}

function normalizedConfig(config: OwnerAuthConfig): Required<OwnerAuthConfig> {
  const ownerToken = config.ownerToken.trim();
  const sessionSecret = config.sessionSecret.trim();
  const ttlSeconds = config.ttlSeconds ?? OWNER_SESSION_TTL_SECONDS;

  if (Buffer.byteLength(ownerToken, "utf8") < 32) {
    configurationError(
      "AUTONOMERCE_WEB_OWNER_TOKEN must contain at least 32 bytes from a cryptographically random source",
    );
  }
  if (sessionSecret.length < 32) {
    configurationError(
      "AUTONOMERCE_WEB_SESSION_SECRET must contain at least 32 characters",
    );
  }
  if (
    !Number.isInteger(ttlSeconds) ||
    ttlSeconds < 60 ||
    ttlSeconds > 60 * 60
  ) {
    configurationError("Owner session lifetime is outside the allowed range");
  }
  if (ownerToken === sessionSecret) {
    configurationError(
      "AUTONOMERCE_WEB_OWNER_TOKEN and AUTONOMERCE_WEB_SESSION_SECRET must be different",
    );
  }

  return { ownerToken, sessionSecret, ttlSeconds };
}

export function resolveOwnerAuthConfig(
  env: Readonly<Record<string, string | undefined>>,
): Required<OwnerAuthConfig> {
  const ownerToken = env.AUTONOMERCE_WEB_OWNER_TOKEN?.trim() ?? "";
  const sessionSecret = env.AUTONOMERCE_WEB_SESSION_SECRET?.trim() ?? "";
  const apiBearerToken = env.AUTONOMERCE_API_BEARER_TOKEN?.trim() ?? "";

  if (!ownerToken || !sessionSecret) {
    configurationError(
      "Owner authentication is not configured",
    );
  }
  if (apiBearerToken && ownerToken === apiBearerToken) {
    configurationError(
      "AUTONOMERCE_WEB_OWNER_TOKEN must be different from AUTONOMERCE_API_BEARER_TOKEN",
    );
  }
  if (apiBearerToken && sessionSecret === apiBearerToken) {
    configurationError(
      "AUTONOMERCE_WEB_SESSION_SECRET must be different from AUTONOMERCE_API_BEARER_TOKEN",
    );
  }

  return normalizedConfig({ ownerToken, sessionSecret });
}

function digest(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}

function constantTimeEqual(left: string, right: string): boolean {
  return timingSafeEqual(digest(left), digest(right));
}

function sign(encodedPayload: string, sessionSecret: string): string {
  return createHmac("sha256", sessionSecret)
    .update(encodedPayload, "utf8")
    .digest("base64url");
}

function encodePayload(payload: OwnerSessionPayload): string {
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
}

function parsePayload(encodedPayload: string): OwnerSessionPayload | null {
  try {
    const value = JSON.parse(
      Buffer.from(encodedPayload, "base64url").toString("utf8"),
    ) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const payload = value as Record<string, unknown>;
    if (
      payload.v !== SESSION_VERSION ||
      !Number.isInteger(payload.iat) ||
      !Number.isInteger(payload.exp) ||
      typeof payload.nonce !== "string" ||
      !/^[a-f0-9]{32}$/.test(payload.nonce)
    ) {
      return null;
    }
    return payload as unknown as OwnerSessionPayload;
  } catch {
    return null;
  }
}

function nowSeconds(nowMs: number): number {
  return Math.floor(nowMs / 1_000);
}

export function createOwnerSession(
  attemptedToken: string,
  config: OwnerAuthConfig,
  nowMs = Date.now(),
): { cookieValue: string; expiresAt: string } {
  const normalized = normalizedConfig(config);
  if (!constantTimeEqual(attemptedToken, normalized.ownerToken)) {
    throw new OwnerAuthenticationError(
      "Owner credentials were rejected",
      401,
      "owner_credentials_invalid",
    );
  }

  const issuedAt = nowSeconds(nowMs);
  const payload: OwnerSessionPayload = {
    v: SESSION_VERSION,
    iat: issuedAt,
    exp: issuedAt + normalized.ttlSeconds,
    nonce: randomBytes(16).toString("hex"),
  };
  const encodedPayload = encodePayload(payload);
  return {
    cookieValue: `${encodedPayload}.${sign(
      encodedPayload,
      normalized.sessionSecret,
    )}`,
    expiresAt: new Date(payload.exp * 1_000).toISOString(),
  };
}

export function verifyOwnerSession(
  cookieValue: string | null | undefined,
  config: OwnerAuthConfig,
  nowMs = Date.now(),
): { authenticated: true; expiresAt: string } | null {
  if (!cookieValue) {
    return null;
  }

  const normalized = normalizedConfig(config);
  const parts = cookieValue.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    return null;
  }
  const [encodedPayload, suppliedSignature] = parts;
  const expectedSignature = sign(encodedPayload, normalized.sessionSecret);
  if (!constantTimeEqual(suppliedSignature, expectedSignature)) {
    return null;
  }

  const payload = parsePayload(encodedPayload);
  if (!payload) {
    return null;
  }
  const current = nowSeconds(nowMs);
  if (
    payload.iat > current + MAX_CLOCK_SKEW_SECONDS ||
    payload.exp <= current ||
    payload.exp <= payload.iat ||
    payload.exp - payload.iat > normalized.ttlSeconds
  ) {
    return null;
  }

  return {
    authenticated: true,
    expiresAt: new Date(payload.exp * 1_000).toISOString(),
  };
}

export function cookieValueFromRequest(request: Request): string | null {
  const cookieHeader = request.headers.get("cookie");
  if (!cookieHeader) {
    return null;
  }

  for (const item of cookieHeader.split(";")) {
    const separator = item.indexOf("=");
    if (separator < 0) {
      continue;
    }
    const name = item.slice(0, separator).trim();
    if (name !== OWNER_SESSION_COOKIE) {
      continue;
    }
    try {
      return decodeURIComponent(item.slice(separator + 1).trim());
    } catch {
      return null;
    }
  }
  return null;
}

export function ownerAuthStatus(
  request: Request,
  config: OwnerAuthConfig,
  nowMs = Date.now(),
): OwnerAuthStatus {
  const session = verifyOwnerSession(
    cookieValueFromRequest(request),
    config,
    nowMs,
  );
  return session
    ? {
        configured: true,
        authenticated: true,
        expiresAt: session.expiresAt,
        reason: null,
      }
    : {
        configured: true,
        authenticated: false,
        expiresAt: null,
        reason: "Owner login is required for LIVE mutations",
      };
}

export function requireOwnerSessionWithConfig(
  request: Request,
  config: OwnerAuthConfig,
  nowMs = Date.now(),
): void {
  if (
    !verifyOwnerSession(cookieValueFromRequest(request), config, nowMs)
  ) {
    throw new OwnerAuthenticationError(
      "Owner session is missing, invalid, or expired",
      401,
      "owner_session_required",
    );
  }
}

export async function authenticateOwnerRequest(
  request: Request,
  config: OwnerAuthConfig,
  nowMs = Date.now(),
): Promise<{
  status: OwnerAuthStatus;
  cookieValue: string;
  expiresAt: string;
}> {
  const { ownerToken } = parseOwnerLoginInput(
    await readProtectedJson(request),
  );
  const session = createOwnerSession(ownerToken, config, nowMs);
  return {
    status: {
      configured: true,
      authenticated: true,
      expiresAt: session.expiresAt,
      reason: null,
    },
    cookieValue: session.cookieValue,
    expiresAt: session.expiresAt,
  };
}

export async function validateOwnerLogoutRequest(
  request: Request,
): Promise<void> {
  await readProtectedJson(request);
}

export function serializeOwnerSessionCookie(
  cookieValue: string,
  expiresAt: string,
  secure: boolean,
  ttlSeconds = OWNER_SESSION_TTL_SECONDS,
): string {
  return [
    `${OWNER_SESSION_COOKIE}=${encodeURIComponent(cookieValue)}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Strict",
    `Max-Age=${ttlSeconds}`,
    `Expires=${new Date(expiresAt).toUTCString()}`,
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}

export function serializeExpiredOwnerSessionCookie(
  secure: boolean,
): string {
  return [
    `${OWNER_SESSION_COOKIE}=`,
    "Path=/",
    "HttpOnly",
    "SameSite=Strict",
    "Max-Age=0",
    "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}
