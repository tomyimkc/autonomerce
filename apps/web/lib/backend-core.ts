const MAX_RESPONSE_BYTES = 1_000_000;

/** Fast-fail bound for ordinary private API metadata and CRUD calls. */
export const BACKEND_DEFAULT_TIMEOUT_MS = 12_000;
/** Exceeds the API's 120-second default Circle execution timeout with margin. */
export const BACKEND_PAY_TIMEOUT_MS = 150_000;
/** Seller execution and validation remain bounded but receive the same live margin. */
export const BACKEND_FULFILL_TIMEOUT_MS = 150_000;
/** Hard ceiling for every private API request initiated by the web server. */
export const BACKEND_MAX_TIMEOUT_MS = 180_000;

export interface BackendClientConfig {
  baseUrl: string;
  bearerToken: string;
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

function normalizeBaseUrl(value: string, variableName: string): string {
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
    parsed.protocol === "http:" &&
    ["127.0.0.1", "localhost", "::1"].includes(parsed.hostname);
  if (
    (parsed.protocol !== "https:" && !localHttp) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new BackendRequestError(
      `${variableName} must be a credential-free HTTP(S) origin or path`,
      503,
      "backend_configuration_invalid",
    );
  }

  return parsed.toString().replace(/\/+$/, "");
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

export class BackendClient {
  private readonly baseUrl: string;
  private readonly bearerToken: string;
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
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${this.bearerToken}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });

      const text = await response.text();
      if (Buffer.byteLength(text, "utf8") > MAX_RESPONSE_BYTES) {
        throw new BackendRequestError(
          "Private API response exceeded the allowed size",
          502,
          "backend_response_too_large",
        );
      }

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
}
