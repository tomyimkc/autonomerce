"use client";

import { useState } from "react";

import type {
  BackendStatus,
  OnboardingInput,
  OnboardingResult,
  ProductMode,
} from "@/lib/api-types";
import { activateSeller } from "@/lib/browser-api";
import { capability, commercialPolicy, seller } from "@/lib/demo-data";
import { formatUsdc } from "@/lib/money";

import { Icon } from "./icons";

const steps = [
  { title: "Connect", shortTitle: "Agent" },
  { title: "Productize", shortTitle: "Offer" },
  { title: "Set policy", shortTitle: "Policy" },
  { title: "Start selling", shortTitle: "Ready" },
] as const;

const initialInput: OnboardingInput = {
  agentName: seller.name,
  agentUrl: seller.agentUrl,
  protocol: "A2A",
  capabilityName: capability.name,
  outcome: capability.outcome,
  priceUsdc: capability.priceUsdc,
  deliverySeconds: capability.deliverySeconds,
  capacityPerHour: capability.capacityPerHour,
  minimumPriceUsdc: commercialPolicy.minimumPriceUsdc,
  maximumDiscountPercent: commercialPolicy.maximumDiscountPercent,
  maximumTasksPerHour: commercialPolicy.maximumTasksPerHour,
  allowedBuyerHost: "buyer.example",
  unattended: true,
};

export function Onboarding({
  mode,
  backendStatus,
  liveResult,
  onActivated,
}: {
  mode: ProductMode;
  backendStatus: BackendStatus;
  liveResult: OnboardingResult | null;
  onActivated: (result: OnboardingResult) => void;
}) {
  const [step, setStep] = useState(0);
  const [input, setInput] = useState(initialInput);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function advance(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step < 2 || mode === "demo") {
      setStep((current) => Math.min(current + 1, steps.length - 1));
      return;
    }
    if (!backendStatus.connected) {
      setError(backendStatus.reason ?? "Private API is disconnected");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await activateSeller(input);
      onActivated(result);
      setStep(3);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Activation failed");
    } finally {
      setBusy(false);
    }
  }

  function update<K extends keyof OnboardingInput>(
    key: K,
    value: OnboardingInput[K],
  ) {
    setInput((current) => ({ ...current, [key]: value }));
  }

  const activeResult = mode === "live" ? liveResult : null;

  return (
    <div className="onboardingGrid">
      <div className="onboardingPanel">
        <div className="onboardingHeader">
          <div>
            <span className="eyebrow eyebrowDark">Seller onboarding</span>
            <h3>Turn an agent into a storefront.</h3>
          </div>
          <span className="fixtureBadge">
            <span aria-hidden="true" />
            {mode === "demo"
              ? "DEMO profile loaded"
              : backendStatus.connected
                ? "LIVE backend connected"
                : "LIVE disconnected"}
          </span>
        </div>

        <ol className="stepper" aria-label="Seller onboarding progress">
          {steps.map((item, index) => (
            <li
              className={`${index === step ? "stepActive" : ""} ${
                index < step ? "stepDone" : ""
              }`}
              key={item.title}
              aria-current={index === step ? "step" : undefined}
            >
              <button type="button" onClick={() => setStep(index)}>
                <span className="stepNumber" aria-hidden="true">
                  {index < step ? <Icon name="check" width={14} height={14} /> : index + 1}
                </span>
                <span>
                  <strong>{item.shortTitle}</strong>
                  <small>{item.title}</small>
                </span>
              </button>
            </li>
          ))}
        </ol>

        <form onSubmit={advance}>
          <div className="onboardingBody" aria-live="polite">
            {step === 0 ? (
              <div className="formStage">
                <StageIntro
                  icon="link"
                  title="Connect your seller agent"
                  body={
                    mode === "demo"
                      ? "Inspect the public-safe fixture without sending a request."
                      : "The browser sends this to the same-origin proxy; the API bearer token stays server-only."
                  }
                />
                <div className="formGrid">
                  <Field label="Agent name">
                    <input
                      name="agentName"
                      value={input.agentName}
                      onChange={(event) => update("agentName", event.target.value)}
                    />
                  </Field>
                  <Field label="Public HTTPS agent endpoint">
                    <input
                      name="agentUrl"
                      value={input.agentUrl}
                      onChange={(event) => update("agentUrl", event.target.value)}
                    />
                  </Field>
                </div>
                <fieldset className="protocolField">
                  <legend>Interface</legend>
                  <div className="segmentedControl">
                    {(["A2A", "MCP", "OpenAPI"] as const).map((protocol) => (
                      <button
                        className={input.protocol === protocol ? "selected" : ""}
                        type="button"
                        aria-pressed={input.protocol === protocol}
                        onClick={() => update("protocol", protocol)}
                        key={protocol}
                      >
                        {protocol}
                      </button>
                    ))}
                  </div>
                </fieldset>
              </div>
            ) : null}

            {step === 1 ? (
              <div className="formStage">
                <StageIntro
                  icon="sparkles"
                  title="Productize the capability"
                  body="Define the outcome and bounded price. LIVE mode uses the SKU returned by the backend."
                />
                <Field label="Sellable outcome">
                  <textarea
                    name="outcome"
                    rows={3}
                    value={input.outcome}
                    onChange={(event) => update("outcome", event.target.value)}
                  />
                </Field>
                <div className="formGrid formGridThree">
                  <NumberField
                    label="List price"
                    value={input.priceUsdc}
                    suffix="USDC"
                    onChange={(value) => update("priceUsdc", value)}
                  />
                  <NumberField
                    label="Delivery SLA"
                    value={String(input.deliverySeconds)}
                    suffix="sec"
                    onChange={(value) => update("deliverySeconds", Number(value))}
                  />
                  <NumberField
                    label="Capacity"
                    value={String(input.capacityPerHour)}
                    suffix="/ hr"
                    onChange={(value) => update("capacityPerHour", Number(value))}
                  />
                </div>
              </div>
            ) : null}

            {step === 2 ? (
              <div className="formStage">
                <StageIntro
                  icon="shield"
                  title="Bind deterministic policy"
                  body="Owner limits are sent to the backend before any order can run."
                />
                <div className="formGrid formGridThree">
                  <NumberField
                    label="Price floor"
                    value={input.minimumPriceUsdc}
                    suffix="USDC"
                    onChange={(value) => update("minimumPriceUsdc", value)}
                  />
                  <NumberField
                    label="Max discount"
                    value={String(input.maximumDiscountPercent)}
                    suffix="%"
                    onChange={(value) =>
                      update("maximumDiscountPercent", Number(value))
                    }
                  />
                  <NumberField
                    label="Hourly limit"
                    value={String(input.maximumTasksPerHour)}
                    suffix="jobs"
                    onChange={(value) =>
                      update("maximumTasksPerHour", Number(value))
                    }
                  />
                </div>
                <Field label="Allowed buyer host">
                  <input
                    name="allowedBuyerHost"
                    value={input.allowedBuyerHost}
                    onChange={(event) =>
                      update("allowedBuyerHost", event.target.value)
                    }
                  />
                </Field>
                {error ? <p className="liveError">{error}</p> : null}
              </div>
            ) : null}

            {step === 3 ? (
              <div className="readyStage">
                <span className="readyMark">
                  <Icon name="store" width={28} height={28} />
                </span>
                <span className="eyebrow eyebrowDark">
                  {mode === "demo" ? "DEMO ready" : "LIVE backend receipt"}
                </span>
                <h4>{activeResult?.seller.name ?? seller.name} has a commercial surface.</h4>
                <p>
                  {mode === "demo"
                    ? "This is the unchanged credential-free replay."
                    : "The IDs below came from the private backend, not a browser fixture."}
                </p>
                <div className="readyChecks">
                  {(activeResult
                    ? [
                        `seller ${activeResult.sellerId}`,
                        `capability ${activeResult.capabilityId}`,
                        `SKU ${activeResult.skuId}`,
                        `policy ${activeResult.policyId}`,
                      ]
                    : [
                        "Public agent manifest",
                        "Machine-readable SKU",
                        "Bounded commercial policy",
                        "No wallets charged",
                      ]
                  ).map((item) => (
                    <span key={item}>
                      <Icon name="check" width={14} height={14} />
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="onboardingFooter">
            <button
              className="button buttonQuiet"
              type="button"
              onClick={() => setStep((current) => Math.max(0, current - 1))}
              disabled={step === 0 || busy}
            >
              Back
            </button>
            {step < steps.length - 1 ? (
              <button
                className="button buttonDark"
                type="submit"
                disabled={busy || (mode === "live" && step === 2 && !backendStatus.connected)}
              >
                {busy
                  ? "Connecting…"
                  : step === 2
                    ? mode === "demo"
                      ? "Activate DEMO seller"
                      : "Activate LIVE seller"
                    : "Continue"}
                <Icon name="arrow-right" width={17} height={17} />
              </button>
            ) : (
              <a className="button buttonDark" href="#operations">
                {mode === "demo" ? "Watch a demo order" : "Run a LIVE order"}
                <Icon name="arrow-right" width={17} height={17} />
              </a>
            )}
          </div>
        </form>
      </div>

      <CapabilityCard mode={mode} input={input} result={activeResult} />
    </div>
  );
}

function StageIntro({
  icon,
  title,
  body,
}: {
  icon: "link" | "sparkles" | "shield";
  title: string;
  body: string;
}) {
  return (
    <div className="formStageIntro">
      <span className="stageIcon">
        <Icon name={icon} width={20} height={20} />
      </span>
      <div>
        <h4>{title}</h4>
        <p>{body}</p>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function NumberField({
  label,
  value,
  suffix,
  onChange,
}: {
  label: string;
  value: string;
  suffix: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <div className="inputSuffix">
        <input
          inputMode="decimal"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <b>{suffix}</b>
      </div>
    </Field>
  );
}

function CapabilityCard({
  mode,
  input,
  result,
}: {
  mode: ProductMode;
  input: OnboardingInput;
  result: OnboardingResult | null;
}) {
  const visiblePrice = result?.sku.basePriceUsdc ?? input.priceUsdc;
  return (
    <article className="capabilityCard">
      <div className="capabilityGlow" aria-hidden="true" />
      <div className="capabilityTop">
        <span className="agentAvatar">
          <Icon name="bot" width={24} height={24} />
        </span>
        <div>
          <span className="eyebrow">Agent capability</span>
          <h3>{result?.seller.name ?? input.agentName}</h3>
          <p>{mode === "demo" ? seller.handle : result?.seller.status ?? "Awaiting activation"}</p>
        </div>
        <span className="statusPill statusPillLive">
          <span aria-hidden="true" />
          {mode === "demo" ? "DEMO" : result ? "LIVE" : "Pending"}
        </span>
      </div>
      <div className="capabilityDivider" />
      <span className="skuLabel">
        {mode === "demo" ? "STATIC DEMO SKU" : "BACKEND SKU"}
      </span>
      <h4>{result?.sku.name ?? input.capabilityName}</h4>
      <p className="capabilityDescription">{result?.sku.outcome ?? input.outcome}</p>
      <div className="capabilityStats">
        <div>
          <small>From</small>
          <strong>
            ${formatUsdc(visiblePrice || "0")}
            <span> USDC</span>
          </strong>
        </div>
        <div>
          <small>Delivery</small>
          <strong>
            ≤ {result?.sku.maximumLatencySeconds ?? input.deliverySeconds}
            <span> sec</span>
          </strong>
        </div>
        <div>
          <small>Capacity</small>
          <strong>
            {result?.sku.capacityPerHour ?? input.capacityPerHour}
            <span> / hour</span>
          </strong>
        </div>
      </div>
      <div className="criteriaBlock">
        <span>Acceptance contract</span>
        <ul>
          {(result?.sku.acceptanceCriteria ?? capability.acceptanceCriteria).map(
            (criterion) => (
              <li key={criterion}>
                <Icon name="check" width={13} height={13} />
                {criterion}
              </li>
            ),
          )}
        </ul>
      </div>
      <div className="capabilityFooter">
        <span>
          <Icon name="code" width={16} height={16} />
          {result?.skuId ?? (mode === "demo" ? capability.skuId : "No backend SKU yet")}
        </span>
        <span>{input.protocol}</span>
      </div>
    </article>
  );
}
