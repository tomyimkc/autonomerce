import { InputValidationError } from "./input-validation";

const MAX_REQUEST_BYTES = 64 * 1024;

function requestOrigins(request: Request): Set<string> {
  const parsedUrl = new URL(request.url);
  const origins = new Set([parsedUrl.origin]);
  const host = request.headers.get("host")?.trim();
  if (
    host &&
    host.length <= 255 &&
    /^[a-z0-9.[\]:-]+$/i.test(host)
  ) {
    const forwardedProtocol = request.headers
      .get("x-forwarded-proto")
      ?.split(",", 1)[0]
      ?.trim()
      .toLowerCase();
    const protocols = new Set([parsedUrl.protocol.replace(":", "")]);
    if (
      forwardedProtocol === "http" ||
      forwardedProtocol === "https"
    ) {
      protocols.add(forwardedProtocol);
    }
    for (const protocol of protocols) {
      origins.add(`${protocol}://${host}`);
    }
  }
  return origins;
}

export async function readProtectedJson(request: Request): Promise<unknown> {
  const contentType = request.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.startsWith("application/json")) {
    throw new InputValidationError("Content-Type must be application/json");
  }

  const origin = request.headers.get("origin");
  const fetchSite = request.headers.get("sec-fetch-site");
  const expectedOrigins = requestOrigins(request);

  if (
    (origin && !expectedOrigins.has(origin)) ||
    (fetchSite && !["same-origin", "none"].includes(fetchSite))
  ) {
    throw new InputValidationError("Cross-origin mutation request rejected");
  }

  if (!origin && fetchSite !== "same-origin") {
    throw new InputValidationError("Mutation request is missing same-origin proof");
  }

  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) {
    throw new InputValidationError("Request body is too large");
  }

  const text = await request.text();
  if (Buffer.byteLength(text, "utf8") > MAX_REQUEST_BYTES) {
    throw new InputValidationError("Request body is too large");
  }

  try {
    return JSON.parse(text);
  } catch {
    throw new InputValidationError("Request body must be valid JSON");
  }
}
