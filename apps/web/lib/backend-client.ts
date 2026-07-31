import "server-only";

import {
  BackendClient,
  BackendRequestError,
  resolveBackendBaseUrl,
} from "./backend-core";

export { BackendRequestError };

export function getBackendClient(): BackendClient {
  const baseUrl = resolveBackendBaseUrl(
    process.env.AUTONOMERCE_API_BASE_URL,
    process.env.AUTONOMERCE_API_PRIVATE_ORIGIN,
  );
  const bearerToken = process.env.AUTONOMERCE_API_BEARER_TOKEN?.trim();

  if (!bearerToken) {
    throw new BackendRequestError(
      "Private API connection is not configured",
      503,
      "backend_configuration_missing",
    );
  }

  return new BackendClient({ baseUrl, bearerToken });
}

export function fundMovingMutationsAllowed(): boolean {
  return process.env.AUTONOMERCE_ALLOW_MOVES_FUNDS === "true";
}
