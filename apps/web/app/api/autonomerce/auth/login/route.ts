import { clientAddressFromRequest } from "@/lib/client-address";
import { InputValidationError } from "@/lib/input-validation";
import { OwnerAuthenticationError } from "@/lib/owner-session-core";
import { loginOwner } from "@/lib/owner-session";
import { OwnerLoginRateLimiter } from "@/lib/request-rate-limit";
import { errorResponse, jsonResponse } from "@/lib/route-response";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const loginLimiter = new OwnerLoginRateLimiter();

export async function POST(request: Request) {
  const address = clientAddressFromRequest(request);
  try {
    loginLimiter.assertAllowed(address);
    const result = await loginOwner(request);
    loginLimiter.recordSuccess(address);
    const response = jsonResponse(result.status);
    response.headers.set("Set-Cookie", result.setCookie);
    return response;
  } catch (error) {
    if (
      error instanceof InputValidationError ||
      (error instanceof OwnerAuthenticationError &&
        error.code === "owner_credentials_invalid")
    ) {
      loginLimiter.recordFailure(address);
    }
    return errorResponse(error);
  }
}
