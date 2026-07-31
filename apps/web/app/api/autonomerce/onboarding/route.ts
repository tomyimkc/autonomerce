import {
  fundMovingMutationsAllowed,
  getBackendClient,
} from "@/lib/backend-client";
import { AutonomerceService } from "@/lib/autonomerce-service";
import { parseOnboardingInput } from "@/lib/input-validation";
import { requireOwnerSession } from "@/lib/owner-session";
import { readProtectedJson } from "@/lib/request-guards";
import { errorResponse, jsonResponse } from "@/lib/route-response";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    requireOwnerSession(request);
    const input = parseOnboardingInput(await readProtectedJson(request));
    const service = new AutonomerceService(
      getBackendClient(),
      fundMovingMutationsAllowed(),
    );
    return jsonResponse(await service.onboard(input), 201);
  } catch (error) {
    return errorResponse(error);
  }
}
