const MAX_RESPONSE_BYTES = 1_000_000;
const MAX_IAM_ID_TOKEN_BYTES = 16_384;
const IAM_ID_TOKEN_MIN_REMAINING_SECONDS = 30;
const IAM_ID_TOKEN_MAX_REMAINING_SECONDS = 65 * 60;
const CLOUD_RUN_METADATA_IDENTITY_URL =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

/** Fast-fail bound for ordinary private API metadata and CRUD calls. */
export const BACKEND_DEFAULT_TIMEOUT_MS = 12_000;
/** Metadata token acquisition must fail well before the private API request bound. */
export const BACKEND_IAM_TOKEN_TIMEOUT_MS = 2_000;
/** Exceeds the API's 120-second default Circle execution timeout with margin. */
export const BACKEND_PAY_TIMEOUT_MS = 150_000;
/** Seller execution and validation remain bounded but receive the same live margin. */
export const BACKEND_FULFILL_TIMEOUT_MS = 150_000;
/** Hard ceiling for every private API request initiated by the web server. */
export const BACKEND_MAX_TIMEOUT_MS = 180_000;

export type BackendIamAuthConfig =
  | { enabled: false }
  | { enabled: true; audience: string };

export interface BackendClientConfig {
  baseUrl: string;
  bearerToken: string;
  iamAuth: BackendIamAuthConfig;
  timeoutMs?: number;
}

export interface BackendRequestOptions {
  timeoutMs?: number;
}

export class BackendRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "BackendRequestError";
  }
}

function normalizeOrigin(
  value: string,
  variableName: string,
  allowLocalHttp: boolean,
): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new BackendRequestError(
      `${variableName} must be an absolute HTTP(S) URL`,
      503,
      "backend_configuration_invalid",
    );
  }

  const localHttp =
    allowLocalHttp &&
    parsed.protocol === "http:" &&
    ["127.0.0.1", "localhost", "::1", "[::1]"].includes(
      parsed.hostname,
    );
  if (
    (parsed.protocol !== "https:" && !localHttp) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new BackendRequestError(
      `${variableName} must be a credential-free ${
        allowLocalHttp ? "HTTPS or loopback HTTP" : "HTTPS"
      } origin without a path`,
      503,
      "backend_configuration_invalid",
    );
  }

  return parsed.origin;
}

function normalizeBaseUrl(value: string, variableName: string): string {
  return normalizeOrigin(value, variableName, true);
}

export function resolveBackendBaseUrl(
  baseUrlValue: string | undefined,
  privateOriginValue: string | undefined,
): string {
  const baseUrl = baseUrlValue?.trim();
  const privateOrigin = privateOriginValue?.trim();

  if (!baseUrl && !privateOrigin) {
    throw new BackendRequestError(
      "Set AUTONOMERCE_API_BASE_URL or AUTONOMERCE_API_PRIVATE_ORIGIN",
      503,
      "backend_configuration_missing",
    );
  }

  const normalizedBaseUrl = baseUrl
    ? normalizeBaseUrl(baseUrl, "AUTONOMERCE_API_BASE_URL")
    : null;
  const normalizedPrivateOrigin = privateOrigin
    ? normalizeBaseUrl(
        privateOrigin,
        "AUTONOMERCE_API_PRIVATE_ORIGIN",
      )
    : null;

  if (
    normalizedBaseUrl &&
    normalizedPrivateOrigin &&
    normalizedBaseUrl !== normalizedPrivateOrigin
  ) {
    throw new BackendRequestError(
      "AUTONOMERCE_API_BASE_URL and AUTONOMERCE_API_PRIVATE_ORIGIN must resolve to the same backend when both are set",
      503,
      "backend_configuration_conflict",
    );
  }

  return normalizedBaseUrl ?? normalizedPrivateOrigin!;
}

function normalizeBackendIamAuth(
  config: BackendIamAuthConfig,
  baseUrl: string,
): BackendIamAuthConfig {
  if (!config.enabled) {
    return { enabled: false };
  }

  const audience = normalizeOrigin(
    config.audience,
    "Backend IAM audience",
    false,
  );
  if (audience !== baseUrl) {
    throw new BackendRequestError(
      "Backend IAM audience must match the private API origin",
      503,
      "backend_configuration_conflict",
    );
  }
  return { enabled: true, audience };
}

export function resolveBackendIamAuth(
  enabledValue: string | undefined,
  audienceValue: string | undefined,
  baseUrl: string,
): BackendIamAuthConfig {
  const enabled = enabledValue?.trim();
  const audience = audienceValue?.trim();

  if (enabled !== "true" && enabled !== "false") {
    throw new BackendRequestError(
      "AUTONOMERCE_API_IAM_AUTH must be explicitly set to true or false",
      503,
      "backend_configuration_missing",
    );
  }
  if (enabled === "false") {
    if (audience) {
      throw new BackendRequestError(
        "AUTONOMERCE_API_IAM_AUDIENCE must be unset when IAM authentication is disabled",
        503,
        "backend_configuration_conflict",
      );
    }
    return { enabled: false };
  }
  if (!audience) {
    throw new BackendRequestError(
      "AUTONOMERCE_API_IAM_AUDIENCE is required when IAM authentication is enabled",
      503,
      "backend_configuration_missing",
    );
  }

  return normalizeBackendIamAuth(
    { enabled: true, audience },
    normalizeBaseUrl(baseUrl, "Backend base URL"),
  );
}

function safeBackendMessage(_value: unknown, status: number): string {
  return status >= 500
    ? "Private API failed to complete the request"
    : "Private API rejected the request";
}

function boundedTimeout(value: number): number {
  if (
    !Number.isInteger(value) ||
    value < 1 ||
    value > BACKEND_MAX_TIMEOUT_MS
  ) {
    throw new BackendRequestError(
      `Backend timeout must be a finite integer between 1 and ${BACKEND_MAX_TIMEOUT_MS} milliseconds`,
      500,
      "backend_timeout_invalid",
    );
  }
  return value;
}

async function readBoundedText(
  response: Response,
  maxBytes: number,
  tooLargeError: () => BackendRequestError,
): Promise<string> {
  const contentLength = response.headers.get("content-length");
  if (
    contentLength !== null &&
    /^\d+$/.test(contentLength) &&
    Number(contentLength) > maxBytes
  ) {
    throw tooLargeError();
  }

  if (!response.body) {
    return "";
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const chunks: string[] = [];
  let bytesRead = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    bytesRead += value.byteLength;
    if (bytesRead > maxBytes) {
      try {
        await reader.cancel();
      } catch {
        // The bounded read has already failed closed; cancellation is best effort.
      }
      throw tooLargeError();
    }
    chunks.push(decoder.decode(value, { stream: true }));
  }
  chunks.push(decoder.decode());
  return chunks.join("");
}

function invalidIamToken(): BackendRequestError {
  return new BackendRequestError(
    "Cloud Run IAM identity token acquisition failed",
    503,
    "backend_iam_token_unavailable",
  );
}

function validateIamIdToken(tokenValue: string, audience: string): string {
  const token = tokenValue.trim();
  if (
    !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(
      token,
    )
  ) {
    throw invalidIamToken();
  }

  let claims: Record<string, unknown>;
  try {
    claims = JSON.parse(
      Buffer.from(token.split(".")[1], "base64url").toString("utf8"),
    ) as Record<string, unknown>;
  } catch {
    throw invalidIamToken();
  }

  const nowSeconds = Math.floor(Date.now() / 1_000);
  const expiresAt = claims.exp;
  if (
    claims.iss !== "https://accounts.google.com" ||
    claims.aud !== audience ||
    typeof expiresAt !== "number" ||
    !Number.isInteger(expiresAt) ||
    expiresAt < nowSeconds + IAM_ID_TOKEN_MIN_REMAINING_SECONDS ||
    expiresAt > nowSeconds + IAM_ID_TOKEN_MAX_REMAINING_SECONDS
  ) {
    throw invalidIamToken();
  }
  return token;
}

export class BackendClient {
  private readonly baseUrl: string;
  private readonly bearerToken: string;
  private readonly iamAuth: BackendIamAuthConfig;
  private readonly timeoutMs: number;

  constructor(
    config: BackendClientConfig,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {
    this.baseUrl = normalizeBaseUrl(
      config.baseUrl,
      "Backend base URL",
    );
    this.bearerToken = config.bearerToken.trim();
    this.iamAuth = normalizeBackendIamAuth(config.iamAuth, this.baseUrl);
    this.timeoutMs = boundedTimeout(
      config.timeoutMs ?? BACKEND_DEFAULT_TIMEOUT_MS,
    );

    if (!this.bearerToken) {
      throw new BackendRequestError(
        "AUTONOMERCE_API_BEARER_TOKEN is required",
        503,
        "backend_configuration_missing",
      );
    }
  }

  get<T>(
    path: string,
    options?: BackendRequestOptions,
  ): Promise<T> {
    return this.request<T>("GET", path, undefined, options);
  }

  post<T>(
    path: string,
    body?: unknown,
    options?: BackendRequestOptions,
  ): Promise<T> {
    return this.request<T>("POST", path, body, options);
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    options?: BackendRequestOptions,
  ): Promise<T> {
    if (!path.startsWith("/") || path.startsWith("//")) {
      throw new BackendRequestError(
        "Backend path must be root-relative",
        500,
        "backend_path_invalid",
      );
    }

    const controller = new AbortController();
    const timeoutMs = boundedTimeout(
      options?.timeoutMs ?? this.timeoutMs,
    );
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const iamHeaders = await this.iamAuthorizationHeaders(
        controller.signal,
      );
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${this.bearerToken}`,
          ...iamHeaders,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });

      const text = await readBoundedText(
        response,
        MAX_RESPONSE_BYTES,
        () =>
          new BackendRequestError(
            "Private API response exceeded the allowed size",
            502,
            "backend_response_too_large",
          ),
      );

      let payload: unknown = null;
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch {
          throw new BackendRequestError(
            "Private API returned invalid JSON",
            502,
            "backend_invalid_json",
          );
        }
      }

      if (!response.ok) {
        throw new BackendRequestError(
          safeBackendMessage(payload, response.status),
          response.status >= 500 ? 502 : response.status,
          "backend_request_failed",
        );
      }

      return payload as T;
    } catch (error) {
      if (error instanceof BackendRequestError) {
        throw error;
      }
      if (error instanceof Error && error.name === "AbortError") {
        throw new BackendRequestError(
          "Private API request timed out",
          504,
          "backend_timeout",
        );
      }
      throw new BackendRequestError(
        "Private API is unreachable",
        503,
        "backend_unreachable",
      );
    } finally {
      clearTimeout(timeout);
    }
  }

  private async iamAuthorizationHeaders(
    requestSignal: AbortSignal,
  ): Promise<Record<string, string>> {
    if (!this.iamAuth.enabled) {
      return {};
    }

    const metadataController = new AbortController();
    let metadataTimedOut = false;
    const abortMetadata = () => metadataController.abort();
    requestSignal.addEventListener("abort", abortMetadata, {
      once: true,
    });
    const metadataTimeout = setTimeout(() => {
      metadataTimedOut = true;
      metadataController.abort();
    }, BACKEND_IAM_TOKEN_TIMEOUT_MS);

    try {
      const metadataUrl = new URL(CLOUD_RUN_METADATA_IDENTITY_URL);
      metadataUrl.searchParams.set("audience", this.iamAuth.audience);
      const response = await this.fetchImpl(metadataUrl, {
        method: "GET",
        cache: "no-store",
        redirect: "error",
        signal: metadataController.signal,
        headers: {
          Accept: "text/plain",
          "Metadata-Flavor": "Google",
        },
      });
      if (!response.ok) {
        throw invalidIamToken();
      }
      const token = await readBoundedText(
        response,
        MAX_IAM_ID_TOKEN_BYTES,
        invalidIamToken,
      );
      return {
        "X-Serverless-Authorization": `Bearer ${validateIamIdToken(
          token,
          this.iamAuth.audience,
        )}`,
      };
    } catch (error) {
      if (error instanceof BackendRequestError) {
        throw error;
      }
      if (error instanceof Error && error.name === "AbortError") {
        if (requestSignal.aborted && !metadataTimedOut) {
          throw new BackendRequestError(
            "Private API request timed out",
            504,
            "backend_timeout",
          );
        }
        throw new BackendRequestError(
          "Cloud Run IAM identity token acquisition timed out",
          504,
          "backend_iam_token_timeout",
        );
      }
      throw invalidIamToken();
    } finally {
      clearTimeout(metadataTimeout);
      requestSignal.removeEventListener("abort", abortMetadata);
    }
  }
}
