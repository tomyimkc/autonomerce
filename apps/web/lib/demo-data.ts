import { averageUsdc, sumUsdc } from "./money";

export type TimelineState =
  | "discovered"
  | "offered"
  | "countered"
  | "authorized"
  | "accepted"
  | "paid"
  | "fulfilling"
  | "delivered";

export type OrderStatus = "settled" | "pending";

export interface TimelineEvent {
  state: TimelineState;
  label: string;
  detail: string;
  time: string;
}

export interface RevenueOrder {
  proposalId: string;
  buyerLabel: string;
  product: string;
  amountUsdc: string;
  status: OrderStatus;
  time: string;
}

export const seller = {
  name: "SignalSmith",
  handle: "@signalsmith.agent",
  description:
    "Turns raw research into concise, source-linked market briefs for autonomous buyers.",
  agentUrl: "https://demo.autonomerce.dev/agents/signalsmith",
  protocol: "A2A",
  status: "selling",
  wallet: "0x64e91d0b14b8f5aa208d6ef86d2c60ea1116a93c",
} as const;

export const capability = {
  capabilityId: "cap_9eaf31c50d82ac07f1b4cdd2",
  skuId: "sku_f4a14ee1e86cf281d450129c",
  name: "Evidence-backed market brief",
  description:
    "A decision-ready competitor brief with source links, risk flags, and an executive summary.",
  outcome: "Structured research brief delivered as Markdown + JSON",
  priceUsdc: "12.00",
  deliverySeconds: 180,
  capacityPerHour: 8,
  tags: ["research", "citations", "market-intelligence"],
  acceptanceCriteria: [
    "At least 5 traceable sources",
    "Every recommendation links to evidence",
    "Markdown and JSON outputs validate",
  ],
} as const;

export const commercialPolicy = {
  policyId: "policy_80ef16fd7c3c322c8dd0867a",
  minimumPriceUsdc: "9.00",
  maximumPriceUsdc: "30.00",
  maximumDiscountPercent: 25,
  maximumOpenProposals: 10,
  maximumTasksPerHour: 8,
  allowedChain: "ARC-TESTNET",
  allowedToken: "USDC",
  unattended: true,
} as const;

export const buyerNeed = {
  needId: "need_ba89e1820e771fe2cf98445d",
  buyerLabel: "GrowthOps Agent · buyer 7F2A",
  desiredOutcome:
    "Compare five AI support vendors for an ecommerce launch decision.",
  maximumPriceUsdc: "14.00",
  optedIn: true,
} as const;

export const proposal = {
  proposalId: "proposal_c3945c22e76f4e4b28af3db2",
  revision: 2,
  finalPriceUsdc: "10.50",
  state: "delivered",
  problemObserved: "Vendor research backlog blocking a launch decision",
  offeredOutcome:
    "A five-vendor decision matrix with cited tradeoffs and a ranked recommendation.",
  timeline: [
    {
      state: "discovered",
      label: "Opted-in need discovered",
      detail: "OfferRail matched 3 required tags",
      time: "09:41:08",
    },
    {
      state: "offered",
      label: "Machine-readable offer sent",
      detail: "Revision 1 · 12.00 USDC · 180s SLA",
      time: "09:41:13",
    },
    {
      state: "countered",
      label: "Buyer countered",
      detail: "10.50 USDC · scope unchanged",
      time: "09:41:29",
    },
    {
      state: "authorized",
      label: "Policy authorized",
      detail: "Price floor and 25% discount bound passed",
      time: "09:41:29",
    },
    {
      state: "accepted",
      label: "Proposal accepted",
      detail: "Revision 2 · no per-payment human approval",
      time: "09:41:31",
    },
    {
      state: "paid",
      label: "Circle payment confirmed",
      detail: "10.50 USDC on Arc Testnet",
      time: "09:41:48",
    },
    {
      state: "fulfilling",
      label: "Seller agent fulfilled",
      detail: "Artifact produced in 94 seconds",
      time: "09:43:22",
    },
    {
      state: "delivered",
      label: "Contract validated",
      detail: "3 of 3 acceptance checks passed",
      time: "09:43:25",
    },
  ] satisfies TimelineEvent[],
} as const;

export const payment = {
  paymentId: "payment_0f8b2f53f1abaad49871ce44",
  proposalId: proposal.proposalId,
  state: "confirmed",
  amountUsdc: proposal.finalPriceUsdc,
  chain: "ARC-TESTNET",
  payerWallet: "0xf912a906e3fc40a8afb90c23ec49639ca6207a37",
  payeeWallet: seller.wallet,
  transactionHash:
    "0xd9b463eaee57496a4d6b497ac5827ef34343b905105860387490ab603af437dc",
  confirmedAt: "2026-07-31T09:41:48Z",
} as const;

export const fulfillment = {
  fulfillmentId: "fulfillment_6871b20a86c7c1fe469275bc",
  proposalId: proposal.proposalId,
  paymentId: payment.paymentId,
  accepted: true,
  validator: "contract-validator/v1",
  artifactHash:
    "sha256:71cdf0a99be58d639417bd4e15f3ba370993360503cfd32d13ef90b888b82c4b",
  deliveredAt: "2026-07-31T09:43:25Z",
  acceptanceResults: [
    { label: "Five vendors compared", passed: true },
    { label: "Source links resolvable", passed: true },
    { label: "JSON schema valid", passed: true },
  ],
} as const;

export const revenueOrders = [
  {
    proposalId: proposal.proposalId,
    buyerLabel: "GrowthOps · 7F2A",
    product: "Market brief",
    amountUsdc: "10.50",
    status: "settled",
    time: "Today, 09:43",
  },
  {
    proposalId: "proposal_d5dd8c122789ee0f90d870e1",
    buyerLabel: "ScoutDesk · 91BB",
    product: "Competitor scan",
    amountUsdc: "18.00",
    status: "settled",
    time: "Today, 08:17",
  },
  {
    proposalId: "proposal_1a558449130156af4b2e1b0e",
    buyerLabel: "LaunchPilot · 02EC",
    product: "Market brief",
    amountUsdc: "12.00",
    status: "settled",
    time: "Yesterday, 18:42",
  },
  {
    proposalId: "proposal_d1f01fe945f4de4dc749ee84",
    buyerLabel: "VentureMap · A71C",
    product: "Category map",
    amountUsdc: "24.50",
    status: "settled",
    time: "Yesterday, 14:08",
  },
  {
    proposalId: "proposal_6861861633c9dc5ab7fb38ec",
    buyerLabel: "BriefBot · 604D",
    product: "Competitor scan",
    amountUsdc: "16.00",
    status: "settled",
    time: "Jul 29, 16:22",
  },
  {
    proposalId: "proposal_9184457076673161969808a0",
    buyerLabel: "DemandLab · D190",
    product: "Market brief",
    amountUsdc: "42.00",
    status: "settled",
    time: "Jul 29, 11:51",
  },
  {
    proposalId: "proposal_755b3546e981c74730c9040e",
    buyerLabel: "OpsAtlas · 4BAE",
    product: "Category map",
    amountUsdc: "18.00",
    status: "pending",
    time: "Today, 09:56",
  },
] satisfies RevenueOrder[];

const settledOrders = revenueOrders.filter((order) => order.status === "settled");

export const revenueSummary = {
  totalRevenueUsdc: sumUsdc(
    settledOrders.map((order) => order.amountUsdc),
  ),
  autonomousOrders: settledOrders.length,
  averageOrderUsdc: averageUsdc(
    settledOrders.map((order) => order.amountUsdc),
  ),
  conversionPercent: 68,
  pendingRevenueUsdc: sumUsdc(
    revenueOrders
      .filter((order) => order.status === "pending")
      .map((order) => order.amountUsdc),
  ),
} as const;

export const chartPoints = [
  { day: "Jul 25", x: 24, y: 154 },
  { day: "Jul 26", x: 98, y: 124 },
  { day: "Jul 27", x: 172, y: 137 },
  { day: "Jul 28", x: 246, y: 91 },
  { day: "Jul 29", x: 320, y: 105 },
  { day: "Jul 30", x: 394, y: 62 },
  { day: "Jul 31", x: 468, y: 32 },
] as const;
