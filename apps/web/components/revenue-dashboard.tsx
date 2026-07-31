import type { WorkflowResult } from "@/lib/api-types";
import {
  chartPoints,
  revenueOrders,
  revenueSummary,
} from "@/lib/demo-data";
import { formatUsdc } from "@/lib/money";

import { Icon } from "./icons";

const path = chartPoints.map((point) => `${point.x},${point.y}`).join(" ");
const areaPath = `M ${chartPoints[0].x} 176 L ${path.replaceAll(
  ",",
  " ",
)} L ${chartPoints.at(-1)?.x ?? 468} 176 Z`;

function shortId(value: string) {
  return `${value.slice(0, 12)}…${value.slice(-5)}`;
}

export function RevenueDashboard({
  liveResult,
}: {
  liveResult?: WorkflowResult;
} = {}) {
  if (liveResult) {
    return <LiveRevenueDashboard result={liveResult} />;
  }
  return (
    <div className="dashboardShell">
      <div className="dashboardTopbar">
        <div className="ownerIdentity">
          <span>TS</span>
          <div>
            <strong>Good morning, Taylor</strong>
            <small>Your agent is earning while you build.</small>
          </div>
        </div>
        <div className="dashboardControls">
          <span className="networkBadge">
            <span aria-hidden="true" />
            Arc Testnet
          </span>
          <button type="button" className="dateControl">
            Last 7 days
            <Icon name="chevron-right" width={14} height={14} />
          </button>
        </div>
      </div>

      <div className="metricGrid">
        <MetricCard
          icon="wallet"
          label="Settled revenue"
          value={`$${formatUsdc(revenueSummary.totalRevenueUsdc)}`}
          suffix="USDC"
          delta="+18.4%"
          accent="green"
        />
        <MetricCard
          icon="receipt"
          label="Autonomous orders"
          value={String(revenueSummary.autonomousOrders)}
          suffix="settled"
          delta="+2 this week"
          accent="blue"
        />
        <MetricCard
          icon="trend"
          label="Average order"
          value={`$${formatUsdc(revenueSummary.averageOrderUsdc)}`}
          suffix="USDC"
          delta="+6.8%"
          accent="violet"
        />
        <MetricCard
          icon="zap"
          label="Offer conversion"
          value={`${revenueSummary.conversionPercent}%`}
          suffix="accepted"
          delta="+9 pts"
          accent="amber"
        />
      </div>

      <div className="dashboardMainGrid">
        <article className="chartCard">
          <div className="chartHeader">
            <div>
              <span className="eyebrow eyebrowDark">Revenue</span>
              <h3>Agent earnings</h3>
            </div>
            <div className="chartLegend">
              <span>
                <i />
                Settled USDC
              </span>
              <strong>
                +${formatUsdc(revenueSummary.pendingRevenueUsdc)} pending
              </strong>
            </div>
          </div>

          <div className="chartWrap">
            <div className="chartScale" aria-hidden="true">
              <span>$60</span>
              <span>$40</span>
              <span>$20</span>
              <span>$0</span>
            </div>
            <svg
              className="revenueChart"
              viewBox="0 0 492 196"
              role="img"
              aria-labelledby="revenue-chart-title revenue-chart-description"
            >
              <title id="revenue-chart-title">
                Settled revenue for the last seven days
              </title>
              <desc id="revenue-chart-description">
                Revenue trends upward across the demo week, ending at the
                highest point on July 31.
              </desc>
              <defs>
                <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#45d6a7" stopOpacity=".32" />
                  <stop offset="100%" stopColor="#45d6a7" stopOpacity="0" />
                </linearGradient>
              </defs>
              {[32, 80, 128, 176].map((y) => (
                <line
                  key={y}
                  x1="24"
                  x2="468"
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  strokeDasharray="3 5"
                />
              ))}
              <path d={areaPath} fill="url(#revenueFill)" />
              <polyline
                points={path}
                fill="none"
                stroke="#24b78b"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="3"
              />
              {chartPoints.map((point, index) => (
                <g key={point.day}>
                  <circle
                    cx={point.x}
                    cy={point.y}
                    r={index === chartPoints.length - 1 ? 6 : 4}
                    fill="#f9fbf8"
                    stroke="#24b78b"
                    strokeWidth="3"
                  />
                  <text x={point.x} y="194" textAnchor="middle">
                    {point.day.replace("Jul ", "")}
                  </text>
                </g>
              ))}
            </svg>
          </div>
        </article>

        <article className="autonomyCard">
          <div className="autonomyHalo" aria-hidden="true" />
          <span className="autonomyIcon">
            <Icon name="bot" width={24} height={24} />
          </span>
          <span className="eyebrow">Autonomy report</span>
          <h3>6 orders, zero checkout interruptions.</h3>
          <p>
            Every settled payment was authorized by the same owner policy. No
            one approved an individual transaction.
          </p>
          <dl>
            <div>
              <dt>Policy blocks</dt>
              <dd>1</dd>
            </div>
            <div>
              <dt>Duplicate settlements</dt>
              <dd>0</dd>
            </div>
            <div>
              <dt>Rejected deliveries</dt>
              <dd>0</dd>
            </div>
          </dl>
          <div className="autonomyFoot">
            <Icon name="shield" width={15} height={15} />
            Deterministic controls active
          </div>
        </article>
      </div>

      <article className="ordersCard">
        <div className="ordersHeader">
          <div>
            <span className="eyebrow eyebrowDark">Order ledger</span>
            <h3>Recent autonomous sales</h3>
          </div>
          <button type="button" className="textButton">
            Export receipts
            <Icon name="arrow-up-right" width={15} height={15} />
          </button>
        </div>

        <div className="tableScroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Buyer</th>
                <th scope="col">Product</th>
                <th scope="col">Proposal</th>
                <th scope="col">Time</th>
                <th scope="col">Status</th>
                <th scope="col" className="numericCell">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {revenueOrders.slice(0, 5).map((order) => (
                <tr key={order.proposalId}>
                  <td>
                    <span className="buyerCell">
                      <i aria-hidden="true">{order.buyerLabel.slice(0, 1)}</i>
                      {order.buyerLabel}
                    </span>
                  </td>
                  <td>{order.product}</td>
                  <td>
                    <code>{shortId(order.proposalId)}</code>
                  </td>
                  <td>{order.time}</td>
                  <td>
                    <span
                      className={`orderStatus orderStatus${order.status}`}
                    >
                      <span aria-hidden="true" />
                      {order.status}
                    </span>
                  </td>
                  <td className="numericCell">
                    <strong>{formatUsdc(order.amountUsdc)}</strong>
                    <small> USDC</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </div>
  );
}

function LiveRevenueDashboard({ result }: { result: WorkflowResult }) {
  const metrics = result.metrics;
  const volume = result.backend.movesFunds
    ? metrics.liveSettlementVolumeUsdc
    : metrics.mockedPaymentVolumeUsdc;
  return (
    <div className="dashboardShell">
      <div className="dashboardTopbar">
        <div className="ownerIdentity">
          <span>API</span>
          <div>
            <strong>LIVE backend metrics</strong>
            <small>
              {metrics.metricsId ?? "Backend did not return a metrics ID"}
            </small>
          </div>
        </div>
        <div className="dashboardControls">
          <span className="networkBadge">
            <span aria-hidden="true" />
            {result.backend.mode} · movesFunds={String(result.backend.movesFunds)}
          </span>
        </div>
      </div>
      <div className="metricGrid">
        <MetricCard
          icon="wallet"
          label={result.backend.movesFunds ? "Live settlement volume" : "Mocked volume"}
          value={`$${formatUsdc(volume)}`}
          suffix="USDC"
          delta="backend"
          accent="green"
        />
        <MetricCard
          icon="receipt"
          label="Proposals sent"
          value={String(metrics.proposalsSent)}
          suffix="backend"
          delta="live"
          accent="blue"
        />
        <MetricCard
          icon="trend"
          label="Successful fulfillment"
          value={String(metrics.successfulFulfillment)}
          suffix="accepted"
          delta="receipt"
          accent="violet"
        />
        <MetricCard
          icon="zap"
          label="Policy denials"
          value={String(metrics.policyDenials)}
          suffix="blocked"
          delta="backend"
          accent="amber"
        />
      </div>
      <article className="ordersCard">
        <div className="ordersHeader">
          <div>
            <span className="eyebrow eyebrowDark">Backend evidence</span>
            <h3>Current order identifiers</h3>
          </div>
        </div>
        <div className="liveEvidenceGrid">
          <code>receipt: {result.receipt.receiptId}</code>
          <code>proposal: {result.proposal.proposalId}</code>
          <code>payment: {result.payment.paymentId}</code>
          <code>fulfillment: {result.fulfillment.fulfillmentId}</code>
          <code>metrics: {metrics.metricsId ?? "not returned"}</code>
        </div>
      </article>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  suffix,
  delta,
  accent,
}: {
  icon: "wallet" | "receipt" | "trend" | "zap";
  label: string;
  value: string;
  suffix: string;
  delta: string;
  accent: "green" | "blue" | "violet" | "amber";
}) {
  return (
    <article className={`metricCard metric${accent}`}>
      <span className="metricIcon">
        <Icon name={icon} width={19} height={19} />
      </span>
      <span className="metricDelta">{delta}</span>
      <small>{label}</small>
      <strong>
        {value}
        <span>{suffix}</span>
      </strong>
    </article>
  );
}
