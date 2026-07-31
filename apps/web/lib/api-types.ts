export type ProductMode = "demo" | "live";

export interface OwnerAuthStatus {
  configured: boolean;
  authenticated: boolean;
  expiresAt: string | null;
  reason: string | null;
}

export interface BackendStatus {
  connected: boolean;
  mode: string | null;
  movesFunds: boolean | null;
  mutationsAllowed: boolean;
  service: string | null;
  storage: string | null;
  integrations: Record<string, string>;
  reason: string | null;
}

export interface OnboardingInput {
  agentName: string;
  agentUrl: string;
  protocol: "A2A" | "MCP" | "OpenAPI";
  capabilityName: string;
  outcome: string;
  priceUsdc: string;
  deliverySeconds: number;
  capacityPerHour: number;
  minimumPriceUsdc: string;
  maximumDiscountPercent: number;
  maximumTasksPerHour: number;
  allowedBuyerHost: string;
  unattended: boolean;
}

export interface OnboardingResult {
  sellerId: string;
  capabilityId: string;
  skuId: string;
  policyId: string;
  seller: {
    name: string;
    agentUrl: string;
    sourceKind: string;
    walletAddress: string | null;
    network: string;
    status: string;
  };
  capability: {
    name: string;
    description: string;
    tags: string[];
  };
  sku: {
    name: string;
    outcome: string;
    basePriceUsdc: string;
    maximumLatencySeconds: number;
    capacityPerHour: number;
    acceptanceCriteria: string[];
  };
  policy: {
    minimumPriceUsdc: string;
    maximumPriceUsdc: string;
    maximumDiscountFraction: string;
    maximumTasksPerHour: number;
    allowedBuyerHosts: string[];
    allowedChains: string[];
    allowedToken: string;
    unattended: boolean;
  };
}

export interface WorkflowInput {
  onboarding: Pick<OnboardingResult, "sellerId" | "skuId" | "policyId">;
  ownerWorkflowOperationId: string;
  operationExpiresAt: string;
  buyerAgentUrl: string;
  buyerOptInConfirmed: boolean;
  consentReference: string;
  publicationAuthorized: boolean;
  publicationConsentReference: string | null;
  desiredOutcome: string;
  maximumPriceUsdc: string;
  problemObserved: string;
  offerPriceUsdc: string;
  counterPriceUsdc: string;
  deliverySeconds: number;
}

export type WorkflowTimelineState =
  | "discovered"
  | "offered"
  | "countered"
  | "authorized"
  | "accepted"
  | "paid"
  | "fulfilling"
  | "delivered"
  | "failed";

export interface WorkflowTimelineEvent {
  state: WorkflowTimelineState;
  label: string;
  detail: string;
  time: string;
}

export interface BackendMetrics {
  metricsId: string | null;
  registeredSellerAgents: number;
  activatedSellerAgents: number;
  proposalsSent: number;
  proposalAcceptanceRate: string;
  negotiatedPriceChangeUsdc: string;
  paidTasks: number | null;
  paidTasksStatus: string | null;
  confirmedLivePayments: number;
  mockedPaymentCount: number;
  successfulFulfillment: number;
  usdcRevenue: string | null;
  liveSettlementVolumeUsdc: string;
  mockedPaymentVolumeUsdc: string;
  medianDeliverySeconds: number | null;
  paymentFailures: number;
  policyDenials: number;
  duplicatePaymentCount: number;
  grossMarginUsdc: string | null;
  grossMarginStatus: string | null;
  revenueClassification: string | null;
}

export interface WorkflowResult {
  operation: {
    ownerWorkflowOperationId: string;
    paymentIdempotencyKey: string;
    resumed: boolean;
  };
  backend: BackendStatus;
  prospect: {
    needId: string;
    buyerAgentUrl: string;
    desiredOutcome: string;
    maximumPriceUsdc: string;
  };
  proposal: {
    proposalId: string;
    skuId: string;
    offeredOutcome: string;
    priceUsdc: string;
    deliverySeconds: number;
    state: string;
    revision: number;
  };
  payment: {
    paymentId: string;
    proposalId: string;
    state: string;
    amountUsdc: string;
    chain: string;
    transactionHash: string | null;
    explorerUrl: string | null;
    confirmedAt: string | null;
    mocked: boolean;
  };
  fulfillment: {
    fulfillmentId: string;
    proposalId: string;
    paymentId: string;
    artifactHash: string;
    accepted: boolean;
    validator: string;
    acceptanceResults: Record<string, boolean>;
    deliveredAt: string | null;
  };
  receipt: {
    published: boolean;
    receiptId: string | null;
    proposalId: string;
    anonymizedOrderId: string | null;
    acceptanceVerdict: string;
    publicationConsentReference: string | null;
  };
  metrics: BackendMetrics;
  timeline: WorkflowTimelineEvent[];
}

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
  };
}
