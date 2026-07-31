import type { OnboardingInput, WorkflowInput } from "./api-types";
import { microsToUsdc, usdcToMicros } from "./money";

export class InputValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InputValidationError";
  }
}

function objectValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new InputValidationError("Request body must be a JSON object");
  }
  return value as Record<string, unknown>;
}

function stringValue(
  object: Record<string, unknown>,
  key: string,
  maximumLength: number,
): string {
  const value = object[key];
  if (typeof value !== "string" || !value.trim()) {
    throw new InputValidationError(`${key} is required`);
  }
  const normalized = value.trim();
  if (normalized.length > maximumLength) {
    throw new InputValidationError(`${key} is too long`);
  }
  return normalized;
}

function booleanValue(object: Record<string, unknown>, key: string): boolean {
  if (typeof object[key] !== "boolean") {
    throw new InputValidationError(`${key} must be boolean`);
  }
  return object[key];
}

function nullableStringValue(
  object: Record<string, unknown>,
  key: string,
  maximumLength: number,
): string | null {
  if (object[key] === null || object[key] === undefined) {
    return null;
  }
  return stringValue(object, key, maximumLength);
}

function integerValue(
  object: Record<string, unknown>,
  key: string,
  minimum: number,
  maximum: number,
): number {
  const value = object[key];
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < minimum ||
    value > maximum
  ) {
    throw new InputValidationError(
      `${key} must be an integer between ${minimum} and ${maximum}`,
    );
  }
  return value;
}

function moneyValue(object: Record<string, unknown>, key: string): string {
  const value = stringValue(object, key, 32);
  try {
    usdcToMicros(value);
  } catch {
    throw new InputValidationError(`${key} must be canonical USDC`);
  }
  return value;
}

function publicHttpsUrl(value: string, key: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new InputValidationError(`${key} must be a valid URL`);
  }

  const hostname = parsed.hostname.toLowerCase();
  const looksPrivate =
    hostname === "localhost" ||
    hostname.endsWith(".local") ||
    hostname === "0.0.0.0" ||
    hostname === "::1" ||
    /^127\./.test(hostname) ||
    /^10\./.test(hostname) ||
    /^192\.168\./.test(hostname) ||
    /^169\.254\./.test(hostname) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname);

  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    looksPrivate
  ) {
    throw new InputValidationError(
      `${key} must be a public credential-free HTTPS URL`,
    );
  }
  return parsed.toString();
}

function hostnameValue(
  object: Record<string, unknown>,
  key: string,
): string {
  const value = stringValue(object, key, 253).toLowerCase();
  if (
    value === "localhost" ||
    value.endsWith(".local") ||
    !/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(
      value,
    )
  ) {
    throw new InputValidationError(`${key} must be a valid public hostname`);
  }
  return value;
}

export function parseOnboardingInput(value: unknown): OnboardingInput {
  const object = objectValue(value);
  const protocol = stringValue(object, "protocol", 16);
  if (!["A2A", "MCP", "OpenAPI"].includes(protocol)) {
    throw new InputValidationError("protocol is not supported");
  }

  const minimumPriceUsdc = moneyValue(object, "minimumPriceUsdc");
  const priceUsdc = moneyValue(object, "priceUsdc");
  if (usdcToMicros(minimumPriceUsdc) > usdcToMicros(priceUsdc)) {
    throw new InputValidationError("minimumPriceUsdc cannot exceed priceUsdc");
  }

  return {
    agentName: stringValue(object, "agentName", 160),
    agentUrl: publicHttpsUrl(
      stringValue(object, "agentUrl", 2_048),
      "agentUrl",
    ),
    protocol: protocol as OnboardingInput["protocol"],
    capabilityName: stringValue(object, "capabilityName", 160),
    outcome: stringValue(object, "outcome", 2_000),
    priceUsdc,
    deliverySeconds: integerValue(
      object,
      "deliverySeconds",
      1,
      86_400,
    ),
    capacityPerHour: integerValue(
      object,
      "capacityPerHour",
      1,
      100_000,
    ),
    minimumPriceUsdc,
    maximumDiscountPercent: integerValue(
      object,
      "maximumDiscountPercent",
      0,
      100,
    ),
    maximumTasksPerHour: integerValue(
      object,
      "maximumTasksPerHour",
      1,
      100_000,
    ),
    allowedBuyerHost: hostnameValue(object, "allowedBuyerHost"),
    unattended: booleanValue(object, "unattended"),
  };
}

export function parseWorkflowInput(value: unknown): WorkflowInput {
  const object = objectValue(value);
  const onboardingObject = objectValue(object.onboarding);
  const onboarding = {
    sellerId: stringValue(onboardingObject, "sellerId", 160),
    skuId: stringValue(onboardingObject, "skuId", 160),
    policyId: stringValue(onboardingObject, "policyId", 160),
  };
  const maximumPriceUsdc = moneyValue(object, "maximumPriceUsdc");
  const offerPriceUsdc = moneyValue(object, "offerPriceUsdc");
  const counterPriceUsdc = moneyValue(object, "counterPriceUsdc");

  if (
    usdcToMicros(offerPriceUsdc) > usdcToMicros(maximumPriceUsdc) ||
    usdcToMicros(counterPriceUsdc) > usdcToMicros(maximumPriceUsdc)
  ) {
    throw new InputValidationError("Offer price exceeds the buyer maximum");
  }

  const ownerWorkflowOperationId = stringValue(
    object,
    "ownerWorkflowOperationId",
    64,
  ).toLowerCase();
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      ownerWorkflowOperationId,
    )
  ) {
    throw new InputValidationError(
      "ownerWorkflowOperationId must be a UUIDv4",
    );
  }

  const operationExpiresAt = stringValue(
    object,
    "operationExpiresAt",
    64,
  );
  const operationExpiryMs = Date.parse(operationExpiresAt);
  const now = Date.now();
  if (
    !Number.isFinite(operationExpiryMs) ||
    operationExpiryMs <= now + 60_000 ||
    operationExpiryMs > now + 7 * 24 * 60 * 60 * 1_000
  ) {
    throw new InputValidationError(
      "operationExpiresAt must be between one minute and seven days in the future",
    );
  }

  const consentReference = stringValue(object, "consentReference", 512);
  const publicationAuthorized = booleanValue(
    object,
    "publicationAuthorized",
  );
  const publicationConsentReference = nullableStringValue(
    object,
    "publicationConsentReference",
    512,
  );
  if (publicationAuthorized && !publicationConsentReference) {
    throw new InputValidationError(
      "publicationConsentReference is required for explicit publication authorization",
    );
  }
  if (!publicationAuthorized && publicationConsentReference) {
    throw new InputValidationError(
      "publicationConsentReference requires explicit publication authorization",
    );
  }
  if (
    publicationConsentReference &&
    publicationConsentReference === consentReference
  ) {
    throw new InputValidationError(
      "publicationConsentReference must be distinct from buyer contact consent",
    );
  }

  return {
    onboarding,
    ownerWorkflowOperationId,
    operationExpiresAt: new Date(operationExpiryMs).toISOString(),
    buyerAgentUrl: publicHttpsUrl(
      stringValue(object, "buyerAgentUrl", 2_048),
      "buyerAgentUrl",
    ),
    buyerOptInConfirmed: booleanValue(object, "buyerOptInConfirmed"),
    consentReference,
    publicationAuthorized,
    publicationConsentReference,
    desiredOutcome: stringValue(object, "desiredOutcome", 2_000),
    maximumPriceUsdc,
    problemObserved: stringValue(object, "problemObserved", 2_000),
    offerPriceUsdc,
    counterPriceUsdc,
    deliverySeconds: integerValue(
      object,
      "deliverySeconds",
      1,
      86_400,
    ),
  };
}

export function parseOwnerLoginInput(value: unknown): { ownerToken: string } {
  const object = objectValue(value);
  return {
    ownerToken: stringValue(object, "ownerToken", 4_096),
  };
}

export function maximumPolicyPrice(priceUsdc: string): string {
  return microsToUsdc(usdcToMicros(priceUsdc) * 3n);
}
