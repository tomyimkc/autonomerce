import { createHash } from "node:crypto";

import type {
  BackendMetrics,
  BackendStatus,
  OnboardingInput,
  OnboardingResult,
  WorkflowInput,
  WorkflowResult,
  WorkflowTimelineEvent,
} from "./api-types";
import {
  BACKEND_FULFILL_TIMEOUT_MS,
  BACKEND_PAY_TIMEOUT_MS,
  BackendClient,
  BackendRequestError,
} from "./backend-core";
import { maximumPolicyPrice } from "./input-validation";

type JsonObject = Record<string, unknown>;

function contractError(message: string): never {
  throw new BackendRequestError(
    message,
    502,
    "backend_contract_invalid",
  );
}

function record(value: unknown, label: string): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    contractError(`Private API returned an invalid ${label}`);
  }
  return value as JsonObject;
}

function stringField(
  value: JsonObject,
  key: string,
  label = key,
): string {
  if (typeof value[key] !== "string" || !value[key]) {
    contractError(`Private API omitted ${label}`);
  }
  return value[key];
}

function nullableStringField(value: JsonObject, key: string): string | null {
  if (value[key] === null || value[key] === undefined) {
    return null;
  }
  if (typeof value[key] !== "string") {
    contractError(`Private API returned invalid ${key}`);
  }
  return value[key];
}

function numberField(value: JsonObject, key: string): number {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    contractError(`Private API returned invalid ${key}`);
  }
  return value[key];
}

function nullableNumberField(value: JsonObject, key: string): number | null {
  if (value[key] === null || value[key] === undefined) {
    return null;
  }
  return numberField(value, key);
}

function booleanField(value: JsonObject, key: string): boolean {
  if (typeof value[key] !== "boolean") {
    contractError(`Private API returned invalid ${key}`);
  }
  return value[key];
}

function stringArrayField(value: JsonObject, key: string): string[] {
  const selected = value[key];
  if (
    !Array.isArray(selected) ||
    !selected.every((item) => typeof item === "string")
  ) {
    contractError(`Private API returned invalid ${key}`);
  }
  return selected;
}

function booleanRecordField(
  value: JsonObject,
  key: string,
): Record<string, boolean> {
  const selected = record(value[key], key);
  const entries = Object.entries(selected);
  if (!entries.every(([, item]) => typeof item === "boolean")) {
    contractError(`Private API returned invalid ${key}`);
  }
  return Object.fromEntries(entries) as Record<string, boolean>;
}

function stringMap(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  );
}

function healthMode(health: JsonObject): string | null {
  if (typeof health.paymentMode === "string" && health.paymentMode) {
    return health.paymentMode;
  }
  if (typeof health.mode === "string" && health.mode) {
    return health.mode;
  }
  const payment = health.payment;
  if (
    payment &&
    typeof payment === "object" &&
    !Array.isArray(payment) &&
    typeof (payment as JsonObject).mode === "string"
  ) {
    return (payment as JsonObject).mode as string;
  }
  return null;
}

function healthMovesFunds(health: JsonObject): boolean | null {
  if (typeof health.movesFunds === "boolean") {
    return health.movesFunds;
  }
  const payment = health.payment;
  if (
    payment &&
    typeof payment === "object" &&
    !Array.isArray(payment) &&
    typeof (payment as JsonObject).movesFunds === "boolean"
  ) {
    return (payment as JsonObject).movesFunds as boolean;
  }
  return null;
}

function disconnected(reason: string): BackendStatus {
  return {
    connected: false,
    mode: null,
    movesFunds: null,
    mutationsAllowed: false,
    service: null,
    storage: null,
    integrations: {},
    reason,
  };
}

function timeLabel(): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(new Date());
}

function canonicalUsdc(value: string): string {
  const [whole, fraction = ""] = value.split(".");
  const normalizedFraction = fraction.replace(/0+$/, "");
  return normalizedFraction ? `${whole}.${normalizedFraction}` : whole;
}

export function workflowOperationFingerprint(input: WorkflowInput): string {
  const immutableInput = {
    onboarding: {
      sellerId: input.onboarding.sellerId,
      skuId: input.onboarding.skuId,
      policyId: input.onboarding.policyId,
    },
    ownerWorkflowOperationId: input.ownerWorkflowOperationId,
    operationExpiresAt: input.operationExpiresAt,
    buyerAgentUrl: input.buyerAgentUrl,
    buyerOptInConfirmed: input.buyerOptInConfirmed,
    consentReference: input.consentReference,
    desiredOutcome: input.desiredOutcome,
    maximumPriceUsdc: canonicalUsdc(input.maximumPriceUsdc),
    problemObserved: input.problemObserved,
    offerPriceUsdc: canonicalUsdc(input.offerPriceUsdc),
    counterPriceUsdc: canonicalUsdc(input.counterPriceUsdc),
    deliverySeconds: input.deliverySeconds,
  };
  return createHash("sha256")
    .update(JSON.stringify(immutableInput), "utf8")
    .digest("hex");
}

function operationProblemObserved(input: WorkflowInput): string {
  return [
    input.problemObserved,
    "",
    `Owner workflow operation: ${input.ownerWorkflowOperationId}`,
    `Owner workflow fingerprint: ${workflowOperationFingerprint(input)}`,
  ].join("\n");
}

export function paymentIdempotencyKey(
  ownerWorkflowOperationId: string,
  proposalId: string,
): string {
  const digest = createHash("sha256")
    .update(
      `autonomerce-web-payment-v1\0${ownerWorkflowOperationId}\0${proposalId}`,
      "utf8",
    )
    .digest("hex");
  return `web-payment-v1-${digest}`;
}

function workflowProposal(
  value: unknown,
  input: WorkflowInput,
  buyerNeedId: string,
): JsonObject | null {
  const listing = record(value, "proposal listing");
  if (!Array.isArray(listing.proposals)) {
    contractError("Private API returned invalid proposals");
  }
  const expectedProblem = operationProblemObserved(input);
  const operationMarker =
    `Owner workflow operation: ${input.ownerWorkflowOperationId}`;
  const expectedPrices = new Set([
    canonicalUsdc(input.offerPriceUsdc),
    canonicalUsdc(input.counterPriceUsdc),
  ]);

  for (const candidateValue of listing.proposals) {
    const candidate = record(candidateValue, "proposal");
    if (
      typeof candidate.problemObserved === "string" &&
      candidate.problemObserved.includes(operationMarker) &&
      candidate.problemObserved !== expectedProblem
    ) {
      throw new BackendRequestError(
        "Existing workflow operation has different immutable inputs",
        409,
        "workflow_operation_conflict",
      );
    }
    if (
      candidate.skuId === input.onboarding.skuId &&
      candidate.buyerAgentUrl === input.buyerAgentUrl &&
      candidate.buyerNeedId === buyerNeedId &&
      candidate.problemObserved === expectedProblem &&
      candidate.expiresAt === input.operationExpiresAt &&
      typeof candidate.priceUsdc === "string" &&
      expectedPrices.has(canonicalUsdc(candidate.priceUsdc))
    ) {
      return candidate;
    }
  }
  return null;
}

function proposalById(
  value: unknown,
  proposalId: string,
): JsonObject {
  const listing = record(value, "proposal listing");
  if (!Array.isArray(listing.proposals)) {
    contractError("Private API returned invalid proposals");
  }
  for (const candidateValue of listing.proposals) {
    const candidate = record(candidateValue, "proposal");
    if (candidate.proposalId === proposalId) {
      return candidate;
    }
  }
  contractError(
    `Private API omitted authoritative proposal ${proposalId}`,
  );
}

function parseMetrics(value: unknown): BackendMetrics {
  const metrics = record(value, "metrics response");
  const metricsIdCandidate =
    metrics.metricsId ?? metrics.snapshotId ?? metrics.receiptId ?? null;

  if (
    metricsIdCandidate !== null &&
    typeof metricsIdCandidate !== "string"
  ) {
    contractError("Private API returned invalid metrics ID");
  }

  return {
    metricsId: metricsIdCandidate,
    registeredSellerAgents: numberField(metrics, "registeredSellerAgents"),
    activatedSellerAgents: numberField(metrics, "activatedSellerAgents"),
    proposalsSent: numberField(metrics, "proposalsSent"),
    proposalAcceptanceRate: stringField(metrics, "proposalAcceptanceRate"),
    negotiatedPriceChangeUsdc: stringField(
      metrics,
      "negotiatedPriceChangeUsdc",
    ),
    paidTasks: nullableNumberField(metrics, "paidTasks"),
    paidTasksStatus: nullableStringField(metrics, "paidTasksStatus"),
    confirmedLivePayments: numberField(metrics, "confirmedLivePayments"),
    mockedPaymentCount: numberField(metrics, "mockedPaymentCount"),
    successfulFulfillment: numberField(metrics, "successfulFulfillment"),
    usdcRevenue: nullableStringField(metrics, "usdcRevenue"),
    liveSettlementVolumeUsdc: stringField(
      metrics,
      "liveSettlementVolumeUsdc",
    ),
    mockedPaymentVolumeUsdc: stringField(
      metrics,
      "mockedPaymentVolumeUsdc",
    ),
    medianDeliverySeconds: nullableNumberField(
      metrics,
      "medianDeliverySeconds",
    ),
    paymentFailures: numberField(metrics, "paymentFailures"),
    policyDenials: numberField(metrics, "policyDenials"),
    duplicatePaymentCount: numberField(metrics, "duplicatePaymentCount"),
    grossMarginUsdc: nullableStringField(metrics, "grossMarginUsdc"),
    grossMarginStatus: nullableStringField(metrics, "grossMarginStatus"),
    revenueClassification: nullableStringField(
      metrics,
      "revenueClassification",
    ),
  };
}

export class AutonomerceService {
  constructor(
    private readonly client: BackendClient,
    private readonly allowMovesFunds: boolean,
  ) {}

  async status(): Promise<BackendStatus> {
    let payload: unknown;
    try {
      payload = await this.client.get<unknown>("/health");
    } catch (error) {
      if (error instanceof BackendRequestError) {
        return disconnected(error.message);
      }
      return disconnected("Private API is unreachable");
    }

    const health = record(payload, "health response");
    const service =
      typeof health.service === "string" ? health.service : null;
    const storage =
      typeof health.storage === "string" ? health.storage : null;
    const mode = healthMode(health);
    const movesFunds = healthMovesFunds(health);

    if (health.status !== "ok") {
      return disconnected("Private API health check is not OK");
    }
    if (!mode || movesFunds === null) {
      return disconnected(
        "Private API health must declare paymentMode and movesFunds",
      );
    }

    return {
      connected: true,
      mode,
      movesFunds,
      mutationsAllowed: !movesFunds || this.allowMovesFunds,
      service,
      storage,
      integrations: stringMap(health.integrations),
      reason:
        movesFunds && !this.allowMovesFunds
          ? "Fund-moving workflow is locked. Set the server-only AUTONOMERCE_ALLOW_MOVES_FUNDS=true only behind owner authentication."
          : null,
    };
  }

  private async requireConnected(): Promise<BackendStatus> {
    const status = await this.status();
    if (!status.connected) {
      throw new BackendRequestError(
        status.reason ?? "Private API is disconnected",
        503,
        "backend_disconnected",
      );
    }
    return status;
  }

  async onboard(input: OnboardingInput): Promise<OnboardingResult> {
    await this.requireConnected();

    const seller = record(
      await this.client.post<unknown>("/sellers", {
        name: input.agentName,
        agentUrl: input.agentUrl,
        sourceKind: input.protocol.toLowerCase(),
        network: "ARC-TESTNET",
      }),
      "seller response",
    );
    const sellerId = stringField(seller, "sellerId");

    const capability = record(
      await this.client.post<unknown>(
        `/sellers/${encodeURIComponent(sellerId)}/capabilities`,
        {
          name: input.capabilityName,
          description: input.outcome,
          inputSchema: { type: "object" },
          outputSchema: { type: "object" },
          sourceKind: "owner",
          sourceUrl: input.agentUrl,
          tags: ["agent-service"],
        },
      ),
      "capability response",
    );
    const capabilityId = stringField(capability, "capabilityId");

    const skuResponse = record(
      await this.client.post<unknown>(
        `/sellers/${encodeURIComponent(sellerId)}/skus/preview`,
        {
          capabilityIds: [capabilityId],
          basePriceUsdc: input.priceUsdc,
          maximumLatencySeconds: input.deliverySeconds,
          capacityPerHour: input.capacityPerHour,
          acceptanceCriteria: ["non_empty_artifact"],
          variants: 1,
        },
      ),
      "SKU response",
    );
    if (!Array.isArray(skuResponse.skus) || skuResponse.skus.length < 1) {
      contractError("Private API returned no productized SKU");
    }
    const sku = record(skuResponse.skus[0], "SKU");
    const skuId = stringField(sku, "skuId");

    const policyResponse = record(
      await this.client.post<unknown>(
        `/sellers/${encodeURIComponent(sellerId)}/policies`,
        {
          minimumPriceUsdc: input.minimumPriceUsdc,
          maximumPriceUsdc: maximumPolicyPrice(input.priceUsdc),
          maximumDiscountFraction: (
            input.maximumDiscountPercent / 100
          ).toString(),
          maximumOpenProposals: 10,
          maximumTasksPerHour: input.maximumTasksPerHour,
          allowedBuyerHosts: [input.allowedBuyerHost],
          blockedBuyerHosts: [],
          allowedChains: ["ARC-TESTNET"],
          allowedToken: "USDC",
          unattended: input.unattended,
        },
      ),
      "policy response",
    );
    const policy = record(policyResponse.policy, "policy");
    const policyId = stringField(policy, "policyId");

    return {
      sellerId,
      capabilityId,
      skuId,
      policyId,
      seller: {
        name: stringField(seller, "name"),
        agentUrl: stringField(seller, "agentUrl"),
        sourceKind: stringField(seller, "sourceKind"),
        walletAddress: nullableStringField(seller, "walletAddress"),
        network: stringField(seller, "network"),
        status: stringField(seller, "status"),
      },
      capability: {
        name: stringField(capability, "name"),
        description: stringField(capability, "description"),
        tags: stringArrayField(capability, "tags"),
      },
      sku: {
        name: stringField(sku, "name"),
        outcome: stringField(sku, "outcome"),
        basePriceUsdc: stringField(sku, "basePriceUsdc"),
        maximumLatencySeconds: numberField(
          sku,
          "maximumLatencySeconds",
        ),
        capacityPerHour: numberField(sku, "capacityPerHour"),
        acceptanceCriteria: stringArrayField(
          sku,
          "acceptanceCriteria",
        ),
      },
      policy: {
        minimumPriceUsdc: stringField(policy, "minimumPriceUsdc"),
        maximumPriceUsdc: stringField(policy, "maximumPriceUsdc"),
        maximumDiscountFraction: stringField(
          policy,
          "maximumDiscountFraction",
        ),
        maximumTasksPerHour: numberField(
          policy,
          "maximumTasksPerHour",
        ),
        allowedBuyerHosts: stringArrayField(
          policy,
          "allowedBuyerHosts",
        ),
        allowedChains: stringArrayField(policy, "allowedChains"),
        allowedToken: stringField(policy, "allowedToken"),
        unattended: booleanField(policy, "unattended"),
      },
    };
  }

  async runWorkflow(input: WorkflowInput): Promise<WorkflowResult> {
    const status = await this.requireConnected();
    if (!status.mutationsAllowed) {
      throw new BackendRequestError(
        status.reason ?? "Fund-moving workflow is locked",
        403,
        "moves_funds_locked",
      );
    }
    if (!input.buyerOptInConfirmed) {
      throw new BackendRequestError(
        "Buyer opt-in must be explicitly confirmed",
        400,
        "buyer_opt_in_required",
      );
    }

    const timeline: WorkflowTimelineEvent[] = [];
    const prospect = record(
      await this.client.post<unknown>("/prospects", {
        buyerAgentUrl: input.buyerAgentUrl,
        desiredOutcome: input.desiredOutcome,
        maximumPriceUsdc: input.maximumPriceUsdc,
        requiredTags: [],
        inputPayload: {
          claim: input.desiredOutcome,
          source: input.buyerAgentUrl,
          problemObserved: input.problemObserved,
        },
        optedIn: true,
        consentReference: input.consentReference,
      }),
      "prospect response",
    );
    const needId = stringField(prospect, "needId");
    timeline.push({
      state: "discovered",
      label: "Opted-in need registered",
      detail: needId,
      time: timeLabel(),
    });

    // Replay detection must span the authenticated owner's entire proposal
    // namespace. Scoping this lookup to the caller-supplied seller lets the
    // same owner operation ID escape detection by changing sellerId, which
    // can create a second proposal and therefore a second payment key.
    const proposalListing = await this.client.get<unknown>("/proposals");
    let proposal = workflowProposal(proposalListing, input, needId);
    const resumed = proposal !== null;
    if (!proposal) {
      proposal = record(
        await this.client.post<unknown>("/proposals", {
          sellerId: input.onboarding.sellerId,
          buyerNeedId: needId,
          skuId: input.onboarding.skuId,
          problemObserved: operationProblemObserved(input),
          priceUsdc: input.offerPriceUsdc,
          deliverySeconds: input.deliverySeconds,
          expiresAt: input.operationExpiresAt,
        }),
        "proposal response",
      );
    }
    const proposalId = stringField(proposal, "proposalId");
    timeline.push({
      state: "offered",
      label: resumed
        ? "Existing commercial action resumed"
        : "Machine-readable offer sent",
      detail: `${proposalId} · ${stringField(proposal, "state")}`,
      time: timeLabel(),
    });

    let proposalState = stringField(proposal, "state");
    const counterRequired =
      canonicalUsdc(input.counterPriceUsdc) !==
      canonicalUsdc(input.offerPriceUsdc);
    if (proposalState === "offered" && counterRequired) {
      const counter = record(
        await this.client.post<unknown>(
          `/proposals/${encodeURIComponent(proposalId)}/counter`,
          {
            priceUsdc: input.counterPriceUsdc,
            deliverySeconds: input.deliverySeconds,
          },
        ),
        "counter response",
      );
      proposal = record(counter.proposal, "countered proposal");
      proposalState = stringField(proposal, "state");
      timeline.push({
        state: "countered",
        label: "Buyer counter recorded",
        detail: `${stringField(proposal, "priceUsdc")} USDC`,
        time: timeLabel(),
      });
    }

    const expectedFinalPrice = canonicalUsdc(
      counterRequired ? input.counterPriceUsdc : input.offerPriceUsdc,
    );
    if (
      proposalState !== "offered" &&
      canonicalUsdc(stringField(proposal, "priceUsdc")) !==
        expectedFinalPrice
    ) {
      throw new BackendRequestError(
        "Existing operation proposal does not match the requested final price",
        409,
        "workflow_operation_conflict",
      );
    }

    timeline.push({
      state: "authorized",
      label: "Bound policy authorized",
      detail: input.onboarding.policyId,
      time: timeLabel(),
    });

    if (["offered", "countered"].includes(proposalState)) {
      const accepted = record(
        await this.client.post<unknown>(
          `/proposals/${encodeURIComponent(proposalId)}/accept`,
        ),
        "accept response",
      );
      proposal = record(accepted.proposal, "accepted proposal");
      proposalState = stringField(proposal, "state");
    } else if (
      !["accepted", "paid", "fulfilling", "delivered", "failed"].includes(
        proposalState,
      )
    ) {
      throw new BackendRequestError(
        `Workflow cannot resume proposal state ${proposalState}`,
        409,
        "workflow_state_not_resumable",
      );
    }
    timeline.push({
      state: "accepted",
      label:
        proposalState === "accepted"
          ? "Proposal accepted"
          : "Proposal acceptance already recorded",
      detail: `revision ${numberField(proposal, "revision")}`,
      time: timeLabel(),
    });

    const idempotencyKey = paymentIdempotencyKey(
      input.ownerWorkflowOperationId,
      proposalId,
    );
    const payment = record(
      await this.client.post<unknown>(
        `/proposals/${encodeURIComponent(proposalId)}/pay`,
        {
          idempotencyKey,
          chain: "ARC-TESTNET",
          token: "USDC",
          publicReceipt: false,
        },
        { timeoutMs: BACKEND_PAY_TIMEOUT_MS },
      ),
      "payment response",
    );
    const paymentId = stringField(payment, "paymentId");
    const paymentState = stringField(payment, "state");
    if (paymentState !== "confirmed") {
      throw new BackendRequestError(
        `Payment is ${paymentState}; fulfillment was not started`,
        409,
        "payment_not_confirmed",
      );
    }
    timeline.push({
      state: "paid",
      label: "Payment confirmed",
      detail: `${paymentId} · ${booleanField(payment, "mocked") ? "mocked" : "external"}`,
      time: timeLabel(),
    });

    timeline.push({
      state: "fulfilling",
      label: "Seller fulfillment invoked",
      detail: proposalId,
      time: timeLabel(),
    });
    const fulfillment = record(
      await this.client.post<unknown>(
        `/proposals/${encodeURIComponent(proposalId)}/fulfill`,
        {},
        { timeoutMs: BACKEND_FULFILL_TIMEOUT_MS },
      ),
      "fulfillment response",
    );
    const fulfillmentId = stringField(fulfillment, "fulfillmentId");
    const fulfillmentAccepted = booleanField(fulfillment, "accepted");

    proposal = proposalById(
      await this.client.get<unknown>(
        `/proposals?sellerId=${encodeURIComponent(
          input.onboarding.sellerId,
        )}`,
      ),
      proposalId,
    );
    proposalState = stringField(proposal, "state");
    const expectedProposalState = fulfillmentAccepted
      ? "delivered"
      : "failed";
    if (proposalState !== expectedProposalState) {
      contractError(
        `Private API proposal state did not reflect fulfillment result; expected ${expectedProposalState}`,
      );
    }

    timeline.push({
      state: fulfillmentAccepted ? "delivered" : "failed",
      label: "Contract validation completed",
      detail: `${fulfillmentId} · ${fulfillmentAccepted ? "accepted" : "rejected"}`,
      time: timeLabel(),
    });

    let receipt: JsonObject | null = null;
    if (input.publicationAuthorized) {
      const publicationConsentReference =
        input.publicationConsentReference;
      if (!publicationConsentReference) {
        throw new BackendRequestError(
          "Explicit publication authorization is missing",
          400,
          "publication_authorization_required",
        );
      }
      const publication = record(
        await this.client.post<unknown>(
          `/receipts/${encodeURIComponent(proposalId)}/publish`,
          {
            consentReference: publicationConsentReference,
            fields: [
              "payment",
              "fulfillment",
              "acceptanceVerdict",
            ],
          },
        ),
        "receipt publication response",
      );
      if (
        publication.published !== true ||
        stringField(publication, "proposalId") !== proposalId
      ) {
        contractError(
          "Private API did not confirm receipt publication",
        );
      }
      receipt = record(
        await this.client.get<unknown>(
          `/receipts/${encodeURIComponent(proposalId)}`,
        ),
        "receipt response",
      );
    }
    const metricsValue = await this.client.get<unknown>("/metrics");

    return {
      operation: {
        ownerWorkflowOperationId: input.ownerWorkflowOperationId,
        paymentIdempotencyKey: idempotencyKey,
        resumed,
      },
      backend: status,
      prospect: {
        needId,
        buyerAgentUrl: stringField(prospect, "buyerAgentUrl"),
        desiredOutcome: stringField(prospect, "desiredOutcome"),
        maximumPriceUsdc: stringField(prospect, "maximumPriceUsdc"),
      },
      proposal: {
        proposalId,
        skuId: stringField(proposal, "skuId"),
        offeredOutcome: stringField(proposal, "offeredOutcome"),
        priceUsdc: stringField(proposal, "priceUsdc"),
        deliverySeconds: numberField(proposal, "deliverySeconds"),
        state: stringField(proposal, "state"),
        revision: numberField(proposal, "revision"),
      },
      payment: {
        paymentId,
        proposalId: stringField(payment, "proposalId"),
        state: stringField(payment, "state"),
        amountUsdc: stringField(payment, "amountUsdc"),
        chain: stringField(payment, "chain"),
        transactionHash: nullableStringField(
          payment,
          "transactionHash",
        ),
        explorerUrl: nullableStringField(payment, "explorerUrl"),
        confirmedAt: nullableStringField(payment, "confirmedAt"),
        mocked: booleanField(payment, "mocked"),
      },
      fulfillment: {
        fulfillmentId,
        proposalId: stringField(fulfillment, "proposalId"),
        paymentId: stringField(fulfillment, "paymentId"),
        artifactHash: stringField(fulfillment, "artifactHash"),
        accepted: booleanField(fulfillment, "accepted"),
        validator: stringField(fulfillment, "validator"),
        acceptanceResults: booleanRecordField(
          fulfillment,
          "acceptanceResults",
        ),
        deliveredAt: nullableStringField(fulfillment, "deliveredAt"),
      },
      receipt: {
        published: receipt !== null,
        receiptId: receipt ? stringField(receipt, "receiptId") : null,
        proposalId: receipt
          ? stringField(receipt, "proposalId")
          : proposalId,
        anonymizedOrderId: receipt
          ? stringField(receipt, "anonymizedOrderId")
          : null,
        acceptanceVerdict: receipt
          ? stringField(receipt, "acceptanceVerdict")
          : fulfillmentAccepted
            ? "accepted"
            : "rejected",
        publicationConsentReference: input.publicationAuthorized
          ? input.publicationConsentReference
          : null,
      },
      metrics: parseMetrics(metricsValue),
      timeline,
    };
  }
}
