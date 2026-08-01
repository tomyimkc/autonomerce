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

export type DealCustomerRelationship =
  | "arms_length"
  | "related_party"
  | "self";

export type DealFundingSource =
  | "customer_funded"
  | "founder_sponsored"
  | "reimbursed"
  | "unknown";

export interface DealVariableCostsInput {
  networkFeesUsdc: string;
  infrastructureUsdc: string;
  fulfillmentUsdc: string;
  otherUsdc: string;
}

export interface DealVariableCosts extends DealVariableCostsInput {
  totalUsdc: string;
}

/**
 * Owner-attested deal facts. Payment network, payment confirmation,
 * fulfillment acceptance, and all classification booleans are deliberately
 * omitted: the private API derives them from its authoritative records.
 */
export interface DealEvidenceInput {
  customerId: string | null;
  userId: string | null;
  customerRelationship: DealCustomerRelationship;
  fundingSource: DealFundingSource;
  consentReference: string;
  refundsUsdc: string;
  refundWindowClosed: true;
  variableCosts: DealVariableCostsInput;
  costsMeasured: true;
  measuredAt: string;
  evidenceReference: string;
}

export interface DealEvidenceRecord {
  evidenceId: string;
  proposalId: string;
  ownerId: string;
  customerId: string | null;
  userId: string | null;
  customerRelationship: DealCustomerRelationship;
  fundingSource: DealFundingSource;
  consentReference: string;
  evidenceReference: string;
  relationshipVerified: boolean;
  verifierReference: string;
  refundsUsdc: string;
  refundWindowClosed: boolean;
  refundWindowClosedAt: string;
  variableCosts: DealVariableCosts;
  costsMeasured: boolean;
  measuredAt: string;
  recordedAt: string;
}

export type DealSettlementClass =
  | "unsettled"
  | "offline_mock"
  | "testnet"
  | "mainnet"
  | "unsupported";

export interface DealClassification {
  evidence: DealEvidenceRecord;
  idempotentReplay: boolean;
  settlementClass: DealSettlementClass;
  paymentConfirmed: boolean;
  acceptedFulfillment: boolean;
  externalCustomer: boolean;
  countsAsRevenue: boolean;
  userAcquired: boolean;
  paidUser: boolean;
  paidTask: boolean;
  paidExternalTask: boolean;
  acceptedPaidExternalTask: boolean;
  paymentAmountUsdc: string;
  grossExternalRevenueUsdc: string;
  refundsUsdc: string;
  netExternalRevenueUsdc: string;
  variableCostsUsdc: string;
  excludedPilotSpendUsdc: string;
  grossMarginUsdc: string;
}

export interface BackendMetrics {
  metricsId: string | null;
  registeredSellerAgents: number;
  activatedSellerAgents: number;
  proposalsSent: number;
  proposalAcceptanceRate: string;
  negotiatedPriceChangeUsdc: string;
  paidTasks: number | null;
  paidExternalTasks: number | null;
  acceptedPaidExternalTasks: number | null;
  paidTasksStatus: string | null;
  confirmedLivePayments: number;
  mockedPaymentCount: number;
  unsupportedPaymentCount: number | null;
  successfulFulfillment: number;
  usdcRevenue: string | null;
  liveSettlementVolumeUsdc: string;
  mockedPaymentVolumeUsdc: string;
  unsupportedPaymentVolumeUsdc: string | null;
  medianDeliverySeconds: number | null;
  paymentFailures: number;
  policyDenials: number;
  duplicatePaymentCount: number;
  grossMarginUsdc: string | null;
  grossMarginStatus: string | null;
  revenueClassification: string | null;
  dealEvidenceCount: number | null;
  usersAcquired: number | null;
  payingUsers: number | null;
  acceptedExternalFulfillments: number | null;
  unclassifiedConfirmedPayments: number | null;
  grossExternalRevenueUsdc: string | null;
  refundsUsdc: string | null;
  netExternalRevenueUsdc: string | null;
  variableCostsUsdc: string | null;
  excludedPilotSpendUsdc: string | null;
  grossMarginPercent: string | null;
  repeatPurchaseRate: string | null;
  repeatPurchaseRateStatus: string | null;
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
