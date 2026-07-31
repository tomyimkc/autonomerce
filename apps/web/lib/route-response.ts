import { NextResponse } from "next/server";

import type { ApiErrorPayload, BackendStatus } from "./api-types";
import { BackendRequestError } from "./backend-core";
import { InputValidationError } from "./input-validation";
import { OwnerAuthenticationError } from "./owner-session-core";
import { RequestRateLimitError } from "./request-rate-limit";

const NO_STORE_HEADERS = {
  "Cache-Control": "no-store, max-age=0",
  Pragma: "no-cache",
};

export function jsonResponse<T>(value: T, status = 200): NextResponse<T> {
  return NextResponse.json(value, {
    status,
    headers: NO_STORE_HEADERS,
  });
}

export function publicStatusResponse<T>(
  value: T,
  cacheState: "hit" | "miss" | "coalesced",
): NextResponse<T> {
  return NextResponse.json(value, {
    status: 200,
    headers: {
      "Cache-Control": "public, max-age=2, s-maxage=5, stale-while-revalidate=20",
      "X-Autonomerce-Status-Cache": cacheState,
    },
  });
}

export function disconnectedResponse(
  reason: string,
): NextResponse<BackendStatus> {
  return jsonResponse({
    connected: false,
    mode: null,
    movesFunds: null,
    mutationsAllowed: false,
    service: null,
    storage: null,
    integrations: {},
    reason,
  });
}

export function errorResponse(
  error: unknown,
): NextResponse<ApiErrorPayload> {
  if (error instanceof InputValidationError) {
    return jsonResponse(
      { error: { code: "invalid_request", message: error.message } },
      400,
    );
  }
  if (error instanceof BackendRequestError) {
    return jsonResponse(
      { error: { code: error.code, message: error.message } },
      error.status,
    );
  }
  if (error instanceof OwnerAuthenticationError) {
    return jsonResponse(
      { error: { code: error.code, message: error.message } },
      error.status,
    );
  }
  if (error instanceof RequestRateLimitError) {
    const response = jsonResponse(
      { error: { code: error.code, message: error.message } },
      429,
    );
    response.headers.set(
      "Retry-After",
      String(error.retryAfterSeconds),
    );
    return response;
  }
  return jsonResponse(
    {
      error: {
        code: "internal_error",
        message: "The server could not complete the request",
      },
    },
    500,
  );
}
