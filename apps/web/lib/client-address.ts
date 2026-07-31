import { isIP } from "node:net";

export const TRUST_PROXY_HEADERS_ENV =
  "AUTONOMERCE_WEB_TRUST_PROXY_HEADERS";
export const UNKNOWN_CLIENT_ADDRESS = "unknown";

const ADDRESS_HEADERS = [
  "x-vercel-forwarded-for",
  "cf-connecting-ip",
  "x-real-ip",
  "x-forwarded-for",
] as const;

type ServerEnvironment = Readonly<
  Record<string, string | undefined>
>;

export function trustedProxyHeadersEnabled(
  env: ServerEnvironment,
): boolean {
  return env[TRUST_PROXY_HEADERS_ENV]?.trim().toLowerCase() === "true";
}

export function clientAddressFromRequest(
  request: Request,
  env: ServerEnvironment = process.env,
): string {
  // A standard Request does not expose the peer socket address. Forwarding
  // headers are therefore ignored unless the server deployment explicitly
  // guarantees that a trusted edge overwrites them.
  if (!trustedProxyHeadersEnabled(env)) {
    return UNKNOWN_CLIENT_ADDRESS;
  }

  for (const header of ADDRESS_HEADERS) {
    const raw = request.headers.get(header);
    if (!raw) {
      continue;
    }
    const candidate = raw.split(",", 1)[0]?.trim().toLowerCase() ?? "";
    if (candidate && isIP(candidate)) {
      return candidate;
    }
  }
  return UNKNOWN_CLIENT_ADDRESS;
}
