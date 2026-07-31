import assert from "node:assert/strict";
import test from "node:test";

import {
  averageUsdc,
  formatUsdc,
  microsToUsdc,
  sumUsdc,
  usdcToMicros,
} from "../lib/money";
import {
  fulfillment,
  payment,
  proposal,
  revenueSummary,
} from "../lib/demo-data";

test("canonical USDC strings convert without binary-float arithmetic", () => {
  assert.equal(usdcToMicros("10.500001"), 10_500_001n);
  assert.equal(microsToUsdc(10_500_001n), "10.500001");
  assert.equal(formatUsdc("12", 2), "12.00");
});

test("invalid and sub-micro USDC values fail closed", () => {
  for (const value of ["-1", "01.00", "1.0000001", "1e2", " 1.00"]) {
    assert.throws(() => usdcToMicros(value));
  }
});

test("USDC aggregation remains exact", () => {
  assert.equal(sumUsdc(["0.10", "0.20", "10.50"]), "10.8");
  assert.equal(averageUsdc(["10.50", "18.00", "12.00"]), "13.5");
});

test("demo revenue metrics include only settled orders", () => {
  assert.equal(revenueSummary.totalRevenueUsdc, "123");
  assert.equal(revenueSummary.autonomousOrders, 6);
  assert.equal(revenueSummary.averageOrderUsdc, "20.5");
  assert.equal(revenueSummary.pendingRevenueUsdc, "18");
});

test("public workflow fixture uses stable semantic identifiers", () => {
  assert.match(proposal.proposalId, /^proposal_[a-f0-9]{24}$/);
  assert.match(payment.paymentId, /^payment_[a-f0-9]{24}$/);
  assert.match(fulfillment.fulfillmentId, /^fulfillment_[a-f0-9]{24}$/);
  assert.match(payment.payerWallet, /^0x[a-f0-9]{40}$/);
  assert.match(payment.payeeWallet, /^0x[a-f0-9]{40}$/);
  assert.match(payment.transactionHash, /^0x[a-f0-9]{64}$/);
  assert.equal(payment.proposalId, proposal.proposalId);
  assert.equal(fulfillment.paymentId, payment.paymentId);
});
