import {
  fundMovingMutationsAllowed,
  getBackendClient,
} from "@/lib/backend-client";
import { AutonomerceService } from "@/lib/autonomerce-service";
import type { BackendStatus } from "@/lib/api-types";
import { clientAddressFromRequest } from "@/lib/client-address";
import { PublicStatusBroker } from "@/lib/request-rate-limit";
import {
  disconnectedResponse,
  errorResponse,
  publicStatusResponse,
} from "@/lib/route-response";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const statusBroker = new PublicStatusBroker<BackendStatus>();

export async function GET(request: Request) {
  try {
    const result = await statusBroker.get(
      clientAddressFromRequest(request),
      async () => {
        const service = new AutonomerceService(
          getBackendClient(),
          fundMovingMutationsAllowed(),
        );
        return service.status();
      },
    );
    return publicStatusResponse(result.value, result.cache);
  } catch (error) {
    if (error instanceof Error && error.name === "RequestRateLimitError") {
      return errorResponse(error);
    }
    return disconnectedResponse(
      error instanceof Error
        ? error.message
        : "Private API connection is not configured",
    );
  }
}
