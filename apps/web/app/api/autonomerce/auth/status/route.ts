import type { OwnerAuthStatus } from "@/lib/api-types";
import { OwnerAuthenticationError } from "@/lib/owner-session-core";
import { getOwnerAuthStatus } from "@/lib/owner-session";
import { errorResponse, jsonResponse } from "@/lib/route-response";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  try {
    return jsonResponse(getOwnerAuthStatus(request));
  } catch (error) {
    if (
      error instanceof OwnerAuthenticationError &&
      error.code === "owner_auth_configuration_invalid"
    ) {
      const status: OwnerAuthStatus = {
        configured: false,
        authenticated: false,
        expiresAt: null,
        reason: "Owner authentication is not configured",
      };
      return jsonResponse(status);
    }
    return errorResponse(error);
  }
}
