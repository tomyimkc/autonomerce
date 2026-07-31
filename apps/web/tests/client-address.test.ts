import assert from "node:assert/strict";
import test from "node:test";

import {
  clientAddressFromRequest,
  UNKNOWN_CLIENT_ADDRESS,
} from "../lib/client-address";

test("client address ignores spoofable forwarding headers by default", () => {
  const request = new Request("https://web.example/status", {
    headers: {
      "cf-connecting-ip": "203.0.113.11",
      "x-forwarded-for": "198.51.100.7, 192.0.2.1",
      "x-real-ip": "198.51.100.8",
    },
  });

  assert.equal(clientAddressFromRequest(request, {}), UNKNOWN_CLIENT_ADDRESS);
  assert.equal(
    clientAddressFromRequest(request, {
      NEXT_PUBLIC_AUTONOMERCE_WEB_TRUST_PROXY_HEADERS: "true",
    }),
    UNKNOWN_CLIENT_ADDRESS,
  );
});

test("client address uses valid proxy headers only after server opt-in", () => {
  const request = new Request("https://web.example/status", {
    headers: {
      "x-forwarded-for": "203.0.113.12, 192.0.2.2",
    },
  });

  assert.equal(
    clientAddressFromRequest(request, {
      AUTONOMERCE_WEB_TRUST_PROXY_HEADERS: "true",
    }),
    "203.0.113.12",
  );
});

test("trusted proxy mode safely falls back for missing or invalid addresses", () => {
  const request = new Request("https://web.example/status", {
    headers: {
      "x-forwarded-for": "attacker-controlled",
      "x-real-ip": "not-an-ip",
    },
  });

  assert.equal(
    clientAddressFromRequest(request, {
      AUTONOMERCE_WEB_TRUST_PROXY_HEADERS: "true",
    }),
    UNKNOWN_CLIENT_ADDRESS,
  );
});
