 "use client";

import { useState } from "react";

import type {
  BackendStatus,
  OnboardingResult,
  WorkflowInput,
  WorkflowResult,
  WorkflowTimelineState,
} from "@/lib/api-types";
import { runWorkflow } from "@/lib/browser-api";
import {
  buyerNeed,
  capability,
  fulfillment,
  payment,
  proposal,
} from "@/lib/demo-data";
import { formatUsdc } from "@/lib/money";

import { CopyButton } from "./copy-button";
import { Icon, type IconName } from "./icons";

const timelineIcons: Record<WorkflowTimelineState, IconName> = {
    discovered: "discovery",
    offered: "document",
    countered: "layers",
    authorized: "shield",
    accepted: "check",
    paid: "wallet",
    fulfilling: "zap",
    delivered: "receipt",
    failed: "shield",
  };

function truncate(value: string, start = 9, end = 7) {
  return `${value.slice(0, start)}…${value.slice(-end)}`;
}

export function Workflow({
  backendStatus,
  onboarding,
  liveResult,
  onCompleted,
}: {
  backendStatus?: BackendStatus;
  onboarding?: OnboardingResult;
  liveResult?: WorkflowResult | null;
  onCompleted?: (result: WorkflowResult) => void;
} = {}) {
  if (backendStatus && onboarding && onCompleted) {
    return (
      <LiveWorkflow
        backendStatus={backendStatus}
        onboarding={onboarding}
        result={liveResult ?? null}
        onCompleted={onCompleted}
      />
    );
  }
  return <DemoWorkflow />;
}

function DemoWorkflow() {
  return (
    <div className="workflowGrid">
      <article className="timelineCard">
        <div className="cardHeader">
          <div>
            <span className="eyebrow eyebrowDark">OfferRail</span>
            <h3>Proposal timeline</h3>
          </div>
          <span className="machineBadge">
            <Icon name="code" width={14} height={14} />
            Machine-readable
          </span>
        </div>

        <div className="proposalSummary">
          <div className="proposalPrice">
            <small>Agreed price</small>
            <strong>
              ${formatUsdc(proposal.finalPriceUsdc)}
              <span> USDC</span>
            </strong>
          </div>
          <div className="proposalRevision">
            <span>rev {proposal.revision}</span>
            <small>Delivered</small>
          </div>
        </div>

        <div className="needBlock">
          <span className="needIcon">
            <Icon name="bot" width={17} height={17} />
          </span>
          <div>
            <span>Opted-in buyer need</span>
            <p>{buyerNeed.desiredOutcome}</p>
            <small>
              {buyerNeed.buyerLabel} · budget ≤ $
              {formatUsdc(buyerNeed.maximumPriceUsdc)}
            </small>
          </div>
        </div>

        <ol className="timeline">
          {proposal.timeline.map((event, index) => (
            <li
              className={
                event.state === "delivered" ? "timelineItemCurrent" : ""
              }
              key={`${event.state}-${event.time}`}
            >
              <span className="timelineRail" aria-hidden="true">
                <span className="timelineNode">
                  <Icon
                    name={timelineIcons[event.state]}
                    width={14}
                    height={14}
                  />
                </span>
                {index < proposal.timeline.length - 1 ? <i /> : null}
              </span>
              <span className="timelineCopy">
                <strong>{event.label}</strong>
                <small>{event.detail}</small>
              </span>
              <time>{event.time}</time>
            </li>
          ))}
        </ol>

        <div className="identifierRow">
          <code>{truncate(proposal.proposalId, 14, 8)}</code>
          <CopyButton
            compact
            label="Copy ID"
            value={proposal.proposalId}
          />
        </div>
      </article>

      <div className="settlementStack">
        <PaymentCard />
        <FulfillmentCard />
      </div>
    </div>
  );
}

function LiveWorkflow({
  backendStatus,
  onboarding,
  result,
  onCompleted,
}: {
  backendStatus: BackendStatus;
  onboarding: OnboardingResult;
  result: WorkflowResult | null;
  onCompleted: (result: WorkflowResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState<Omit<WorkflowInput, "onboarding">>({
    ownerWorkflowOperationId: "00000000-0000-4000-8000-000000000001",
    operationExpiresAt: new Date(
      Date.now() + 60 * 60 * 1_000,
    ).toISOString(),
    buyerAgentUrl: "https://buyer.example/.well-known/agent-card.json",
    buyerOptInConfirmed: true,
    consentReference: "owner-confirmed:buyer.example:live-order",
    publicationAuthorized: true,
    publicationConsentReference:
      "publication-confirmed:buyer.example:live-order",
    desiredOutcome: buyerNeed.desiredOutcome,
    maximumPriceUsdc: buyerNeed.maximumPriceUsdc,
    problemObserved: proposal.problemObserved,
    offerPriceUsdc: capability.priceUsdc,
    counterPriceUsdc: proposal.finalPriceUsdc,
    deliverySeconds: capability.deliverySeconds,
  });

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onCompleted(
        await runWorkflow({
          ...input,
          onboarding: {
            sellerId: onboarding.sellerId,
            skuId: onboarding.skuId,
            policyId: onboarding.policyId,
          },
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Workflow failed");
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <div className="workflowGrid">
        <article className="timelineCard">
          <div className="cardHeader">
            <div>
              <span className="eyebrow eyebrowDark">LIVE OfferRail</span>
              <h3>Backend proposal timeline</h3>
            </div>
            <span className="machineBadge">{result.receipt.receiptId}</span>
          </div>
          <div className="proposalSummary">
            <div className="proposalPrice">
              <small>Backend confirmed amount</small>
              <strong>
                ${formatUsdc(result.payment.amountUsdc)}
                <span> USDC</span>
              </strong>
            </div>
            <div className="proposalRevision">
              <span>rev {result.proposal.revision}</span>
              <small>{result.receipt.acceptanceVerdict}</small>
            </div>
          </div>
          <ol className="timeline">
            {result.timeline.map((event) => (
              <li key={`${event.state}-${event.time}`}>
                <span className="timelineRail" aria-hidden="true">
                  <span className="timelineNode">
                    <Icon name={timelineIcons[event.state]} width={14} height={14} />
                  </span>
                </span>
                <span className="timelineCopy">
                  <strong>{event.label}</strong>
                  <small>{event.detail}</small>
                </span>
                <time>{event.time}</time>
              </li>
            ))}
          </ol>
          <div className="identifierRow">
            <code>{result.proposal.proposalId}</code>
            <CopyButton compact label="Copy ID" value={result.proposal.proposalId} />
          </div>
        </article>
        <div className="settlementStack">
          <article className="paymentCard">
            <div className="paymentHeader">
              <div className="circleIdentity">
                <span className="circleMark" aria-hidden="true">$</span>
                <span>
                  <strong>Backend payment</strong>
                  <small>{result.backend.mode}</small>
                </span>
              </div>
              <span className="confirmedBadge">
                <Icon name="check" width={13} height={13} />
                {result.payment.mocked ? "Mocked" : "Confirmed"}
              </span>
            </div>
            <div className="paymentAmount">
              <small>movesFunds={String(result.backend.movesFunds)}</small>
              <strong>
                {formatUsdc(result.payment.amountUsdc)}
                <span> USDC</span>
              </strong>
              <span>{result.payment.chain}</span>
            </div>
            <dl className="paymentDetails">
              <div><dt>Payment ID</dt><dd>{result.payment.paymentId}</dd></div>
              <div><dt>Transaction</dt><dd>{result.payment.transactionHash ?? "not returned"}</dd></div>
            </dl>
          </article>
          <article className="receiptCard">
            <div className="receiptHeader">
              <div>
                <span className="eyebrow eyebrowDark">Backend receipt</span>
                <h3>{result.receipt.acceptanceVerdict}</h3>
              </div>
              <span className="receiptSeal"><Icon name="check" width={21} height={21} /></span>
            </div>
            <div className="artifactBlock">
              <span>Receipt ID</span>
              <code>{result.receipt.receiptId}</code>
            </div>
            <div className="artifactBlock">
              <span>Fulfillment ID</span>
              <code>{result.fulfillment.fulfillmentId}</code>
            </div>
            <div className="artifactBlock">
              <span>Metrics ID</span>
              <code>{result.metrics.metricsId ?? "backend did not return an ID"}</code>
            </div>
          </article>
        </div>
      </div>
    );
  }

  return (
    <form className="liveWorkflowForm" onSubmit={submit}>
      <div>
        <span className="eyebrow eyebrowDark">LIVE workflow</span>
        <h3>Run one backend order</h3>
        <p>
          Backend mode <strong>{backendStatus.mode}</strong> · movesFunds=
          <strong>{String(backendStatus.movesFunds)}</strong>. No fixture success is
          shown if this request fails.
        </p>
      </div>
      <div className="formGrid">
        <label className="field">
          <span>Buyer agent URL</span>
          <input
            value={input.buyerAgentUrl}
            onChange={(event) =>
              setInput((current) => ({ ...current, buyerAgentUrl: event.target.value }))
            }
          />
        </label>
        <label className="field">
          <span>Desired outcome</span>
          <input
            value={input.desiredOutcome}
            onChange={(event) =>
              setInput((current) => ({ ...current, desiredOutcome: event.target.value }))
            }
          />
        </label>
        <label className="field">
          <span>Buyer consent reference</span>
          <input
            value={input.consentReference}
            onChange={(event) =>
              setInput((current) => ({
                ...current,
                consentReference: event.target.value,
              }))
            }
          />
        </label>
        <label className="field">
          <span>Publication consent reference</span>
          <input
            value={input.publicationConsentReference ?? ""}
            disabled={!input.publicationAuthorized}
            onChange={(event) =>
              setInput((current) => ({
                ...current,
                publicationConsentReference: event.target.value || null,
              }))
            }
          />
        </label>
        <label className="checkField">
          <input
            type="checkbox"
            checked={input.publicationAuthorized}
            onChange={(event) =>
              setInput((current) => ({
                ...current,
                publicationAuthorized: event.target.checked,
                publicationConsentReference: event.target.checked
                  ? current.publicationConsentReference ||
                    "publication-confirmed:buyer.example:live-order"
                  : null,
              }))
            }
          />
          <span>Publish the redacted receipt under separate authorization</span>
        </label>
      </div>
      {error ? <p className="liveError">{error}</p> : null}
      <button className="button buttonDark" type="submit" disabled={busy || !backendStatus.mutationsAllowed}>
        {busy ? "Running backend workflow…" : "Run LIVE order"}
        <Icon name="arrow-right" width={17} height={17} />
      </button>
    </form>
  );
}

function PaymentCard() {
  return (
    <article className="paymentCard">
      <div className="paymentHeader">
        <div className="circleIdentity">
          <span className="circleMark" aria-hidden="true">
            $
          </span>
          <span>
            <strong>Circle payment</strong>
            <small>USDC settlement</small>
          </span>
        </div>
        <span className="confirmedBadge">
          <Icon name="check" width={13} height={13} />
          Confirmed
        </span>
      </div>

      <div className="paymentAmount">
        <small>Payment received</small>
        <strong>
          {formatUsdc(payment.amountUsdc)}
          <span> USDC</span>
        </strong>
        <span>{payment.chain.replace("-", " ")}</span>
      </div>

      <ol className="paymentProgress" aria-label="Circle payment progress">
        {["Policy authorized", "Submitted", "Confirmed"].map((label, index) => (
          <li key={label}>
            <span>
              <Icon name="check" width={11} height={11} />
            </span>
            <small>{label}</small>
            {index < 2 ? <i /> : null}
          </li>
        ))}
      </ol>

      <dl className="paymentDetails">
        <div>
          <dt>From</dt>
          <dd>{truncate(payment.payerWallet, 8, 6)}</dd>
        </div>
        <div>
          <dt>To seller</dt>
          <dd>{truncate(payment.payeeWallet, 8, 6)}</dd>
        </div>
        <div>
          <dt>Transaction</dt>
          <dd>
            <code>{truncate(payment.transactionHash, 10, 8)}</code>
            <CopyButton
              compact
              label="Copy"
              value={payment.transactionHash}
            />
          </dd>
        </div>
      </dl>

      <div className="trustBoundary">
        <Icon name="shield" width={15} height={15} />
        Payment is confirmed. Delivery is validated separately below.
      </div>
    </article>
  );
}

function FulfillmentCard() {
  return (
    <article className="receiptCard">
      <div className="receiptHeader">
        <div>
          <span className="eyebrow eyebrowDark">Fulfillment receipt</span>
          <h3>Contract accepted</h3>
        </div>
        <span className="receiptSeal">
          <Icon name="check" width={21} height={21} />
        </span>
      </div>

      <div className="receiptMeta">
        <span>
          <Icon name="clock" width={14} height={14} />
          94s fulfillment
        </span>
        <span>
          <Icon name="shield" width={14} height={14} />
          {fulfillment.validator}
        </span>
      </div>

      <ul className="validationList">
        {fulfillment.acceptanceResults.map((result) => (
          <li key={result.label}>
            <span>
              <Icon name="check" width={12} height={12} />
            </span>
            {result.label}
            <strong>PASS</strong>
          </li>
        ))}
      </ul>

      <div className="artifactBlock">
        <span>Artifact fingerprint</span>
        <code>{truncate(fulfillment.artifactHash, 18, 10)}</code>
      </div>

      <div className="receiptActions">
        <CopyButton
          value={JSON.stringify(
            {
              fulfillmentId: fulfillment.fulfillmentId,
              proposalId: fulfillment.proposalId,
              paymentId: fulfillment.paymentId,
              accepted: fulfillment.accepted,
              artifactHash: fulfillment.artifactHash,
              deliveredAt: fulfillment.deliveredAt,
            },
            null,
            2,
          )}
          label="Copy public receipt"
        />
        <span className="receiptId">
          <Icon name="receipt" width={14} height={14} />
          {truncate(fulfillment.fulfillmentId, 12, 6)}
        </span>
      </div>
    </article>
  );
}
