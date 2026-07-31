import "server-only";

import type { OwnerAuthStatus } from "./api-types";
import {
  authenticateOwnerRequest,
  ownerAuthStatus,
  requireOwnerSessionWithConfig,
  resolveOwnerAuthConfig,
  serializeExpiredOwnerSessionCookie,
  serializeOwnerSessionCookie,
  validateOwnerLogoutRequest,
} from "./owner-session-core";

function config() {
  return resolveOwnerAuthConfig(process.env);
}

function secureCookie(request: Request): boolean {
  return (
    process.env.NODE_ENV === "production" ||
    new URL(request.url).protocol === "https:"
  );
}

export function getOwnerAuthStatus(request: Request): OwnerAuthStatus {
  return ownerAuthStatus(request, config());
}

export function requireOwnerSession(request: Request): void {
  requireOwnerSessionWithConfig(request, config());
}

export async function loginOwner(
  request: Request,
): Promise<{ status: OwnerAuthStatus; setCookie: string }> {
  const ownerConfig = config();
  const result = await authenticateOwnerRequest(request, ownerConfig);
  return {
    status: result.status,
    setCookie: serializeOwnerSessionCookie(
      result.cookieValue,
      result.expiresAt,
      secureCookie(request),
      ownerConfig.ttlSeconds,
    ),
  };
}

export async function logoutOwner(
  request: Request,
): Promise<{ status: OwnerAuthStatus; setCookie: string }> {
  await validateOwnerLogoutRequest(request);
  return {
    status: {
      configured: true,
      authenticated: false,
      expiresAt: null,
      reason: "Owner session ended",
    },
    setCookie: serializeExpiredOwnerSessionCookie(secureCookie(request)),
  };
}
