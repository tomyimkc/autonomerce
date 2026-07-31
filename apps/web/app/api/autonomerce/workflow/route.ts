import {
  fundMovingMutationsAllowed,
  getBackendClient,
} from "@/lib/backend-client";
import { AutonomerceService } from "@/lib/autonomerce-service";
import { parseWorkflowInput } from "@/lib/input-validation";
import { requireOwnerSession } from "@/lib/owner-session";
import { readProtectedJson } from "@/lib/request-guards";
import { errorResponse, jsonResponse } from "@/lib/route-response";
import { withWorkflowOperationLock } from "@/lib/workflow-operation";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    requireOwnerSession(request);
    const input = parseWorkflowInput(await readProtectedJson(request));
    const service = new AutonomerceService(
      getBackendClient(),
      fundMovingMutationsAllowed(),
    );
    return jsonResponse(
      await withWorkflowOperationLock(
        input.ownerWorkflowOperationId,
        () => service.runWorkflow(input),
      ),
      201,
    );
  } catch (error) {
    return errorResponse(error);
  }
}
