"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  BackendStatus,
  OnboardingResult,
  OwnerAuthStatus,
  ProductMode,
  WorkflowResult,
} from "@/lib/api-types";
import {
  getBackendStatus,
  getOwnerAuthStatus,
  loginOwner,
  logoutOwner,
  OWNER_AUTH_REQUIRED_EVENT,
} from "@/lib/browser-api";
import { proposal, seller } from "@/lib/demo-data";
import { formatUsdc } from "@/lib/money";

import { Brand } from "./brand";
import { Icon } from "./icons";
import { Onboarding } from "./onboarding";
import { RevenueDashboard } from "./revenue-dashboard";
import { Workflow } from "./workflow";

const INITIAL_LIVE_STATUS: BackendStatus = {
  connected: false,
  mode: null,
  movesFunds: null,
  mutationsAllowed: false,
  service: null,
  storage: null,
  integrations: {},
  reason: "Checking the private API connection…",
};

const INITIAL_OWNER_AUTH: OwnerAuthStatus = {
  configured: true,
  authenticated: false,
  expiresAt: null,
  reason: "Checking the owner session…",
};

function ownerLockedStatus(reason: string): BackendStatus {
  return {
    ...INITIAL_LIVE_STATUS,
    reason,
  };
}

export function AutonomerceApp() {
  const [mode, setMode] = useState<ProductMode>("demo");
  const [ownerAuth, setOwnerAuth] =
    useState<OwnerAuthStatus>(INITIAL_OWNER_AUTH);
  const [backendStatus, setBackendStatus] =
    useState<BackendStatus>(INITIAL_LIVE_STATUS);
  const [onboarding, setOnboarding] = useState<OnboardingResult | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowResult | null>(null);

  const refreshBackend = useCallback(async () => {
    setBackendStatus(INITIAL_LIVE_STATUS);
    try {
      setBackendStatus(await getBackendStatus());
    } catch (error) {
      setBackendStatus({
        ...INITIAL_LIVE_STATUS,
        reason:
          error instanceof Error
            ? error.message
            : "Private API status request failed",
      });
    }
  }, []);

  const requireOwnerLogin = useCallback((reason: string) => {
    setOwnerAuth({
      configured: true,
      authenticated: false,
      expiresAt: null,
      reason,
    });
    setBackendStatus(ownerLockedStatus(reason));
    setOnboarding(null);
    setWorkflow(null);
  }, []);

  const refreshLiveAccess = useCallback(async () => {
    setOwnerAuth(INITIAL_OWNER_AUTH);
    setBackendStatus(
      ownerLockedStatus("Checking the owner session…"),
    );
    try {
      const status = await getOwnerAuthStatus();
      setOwnerAuth(status);
      if (status.authenticated) {
        await refreshBackend();
      } else {
        setBackendStatus(
          ownerLockedStatus(
            status.reason ?? "Owner login is required for LIVE mutations",
          ),
        );
      }
    } catch (error) {
      const reason =
        error instanceof Error
          ? error.message
          : "Owner session status request failed";
      setOwnerAuth({
        configured: false,
        authenticated: false,
        expiresAt: null,
        reason,
      });
      setBackendStatus(ownerLockedStatus(reason));
    }
  }, [refreshBackend]);

  useEffect(() => {
    if (mode === "live") {
      void refreshLiveAccess();
    }
  }, [mode, refreshLiveAccess]);

  useEffect(() => {
    function onOwnerAuthRequired() {
      requireOwnerLogin("Owner session expired. Log in again.");
    }
    window.addEventListener(
      OWNER_AUTH_REQUIRED_EVENT,
      onOwnerAuthRequired,
    );
    return () => {
      window.removeEventListener(
        OWNER_AUTH_REQUIRED_EVENT,
        onOwnerAuthRequired,
      );
    };
  }, [requireOwnerLogin]);

  async function authenticateOwner(ownerToken: string) {
    const status = await loginOwner(ownerToken);
    setOwnerAuth(status);
    await refreshBackend();
  }

  async function endOwnerSession() {
    const status = await logoutOwner();
    setOwnerAuth(status);
    setBackendStatus(
      ownerLockedStatus(
        status.reason ?? "Owner login is required for LIVE mutations",
      ),
    );
    setOnboarding(null);
    setWorkflow(null);
  }


  function switchMode(nextMode: ProductMode) {
    setMode(nextMode);
    if (nextMode === "demo") {
      document.querySelector("#operations")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }

  function openDemo() {
    switchMode("demo");
    window.setTimeout(() => {
      document.querySelector("#operations")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 0);
  }

  return (
    <>
      <a className="skipLink" href="#main-content">
        Skip to main content
      </a>

      <header className="siteHeader">
        <div className="shell headerInner">
          <a href="#top" aria-label="Autonomerce home">
            <Brand />
          </a>
          <nav aria-label="Primary navigation">
            <a href="#how-it-works">How it works</a>
            <a href="#onboarding">For sellers</a>
            <a href="#revenue">Revenue</a>
          </nav>
          <div className="headerActions">
            <span className={`modeChip modeChip${mode}`}>
              {mode.toUpperCase()}
            </span>
            <span className="demoLabel">
              {mode === "demo"
                ? "Static replay"
                : ownerAuth.authenticated
                  ? "Owner session"
                  : "Owner locked"}
            </span>
            <button
              className={`switch ${mode === "live" ? "switchOn" : ""}`}
              type="button"
              role="switch"
              aria-checked={mode === "live"}
              aria-label="Toggle between DEMO and LIVE backend mode"
              onClick={() =>
                switchMode(mode === "demo" ? "live" : "demo")
              }
            >
              <span />
            </button>
            <a className="button buttonDark buttonSmall" href="#onboarding">
              Add your agent
              <Icon name="arrow-right" width={15} height={15} />
            </a>
          </div>
        </div>
      </header>

      <ModeBanner
        mode={mode}
        ownerAuth={ownerAuth}
        status={backendStatus}
        onRetry={refreshLiveAccess}
      />
      {mode === "live" ? (
        <OwnerAccessPanel
          status={ownerAuth}
          onLogin={authenticateOwner}
          onLogout={endOwnerSession}
        />
      ) : null}

      <main id="main-content">
        <section className="hero" id="top">
          <div className="heroNoise" aria-hidden="true" />
          <div className="shell heroGrid">
            <div className="heroCopy">
              <span className="launchBadge">
                <Icon name="sparkles" width={14} height={14} />
                Autonomous commerce for every agent
              </span>
              <h1>
                Give your agent <span>a sales department.</span>
              </h1>
              <p>
                Autonomerce turns AI capabilities into sellable outcomes—then
                discovers buyers, negotiates inside policy, gets paid in USDC,
                and delivers the work.
              </p>
              <div className="heroActions">
                <a className="button buttonPrimary" href="#onboarding">
                  Productize your agent
                  <Icon name="arrow-right" width={18} height={18} />
                </a>
                <button className="button buttonGhost" type="button" onClick={openDemo}>
                  <span className="playIcon">
                    <Icon name="eye" width={15} height={15} />
                  </span>
                  Watch a demo order
                </button>
              </div>
              <div className="heroProof">
                <span>
                  <Icon name="shield" width={15} height={15} />
                  Owner policy, not AI judgment
                </span>
                <span>
                  <Icon name="lock" width={15} height={15} />
                  {mode === "demo"
                    ? "No credentials in DEMO mode"
                    : "API bearer token stays server-only"}
                </span>
              </div>
            </div>

            <CommerceRailPreview
              mode={mode}
              status={backendStatus}
              workflow={workflow}
            />
          </div>

          <div className="shell integrationStrip">
            <span>Works with your existing agent</span>
            <div>
              <strong>
                <Icon name="bot" width={18} height={18} />
                A2A
              </strong>
              <strong>
                <Icon name="layers" width={18} height={18} />
                MCP
              </strong>
              <strong>
                <Icon name="code" width={18} height={18} />
                OpenAPI
              </strong>
              <i />
              <strong className="geminiPartner">
                <Icon name="sparkles" width={18} height={18} />
                Gemini
              </strong>
              <strong className="circlePartner">
                <span aria-hidden="true">$</span>
                Circle
              </strong>
            </div>
          </div>
        </section>

        <section className="howSection" id="how-it-works">
          <div className="shell">
            <div className="sectionIntro centeredIntro">
              <span className="eyebrow eyebrowGreen">One autonomous rail</span>
              <h2>From latent capability to verified revenue.</h2>
              <p>
                Gemini helps shape the offer. Deterministic policy authorizes
                the deal. Circle settles it. The seller agent earns only after
                a separate fulfillment check.
              </p>
            </div>

            <ol className="flowSteps">
              <FlowStep
                number="01"
                icon="sparkles"
                title="Productize"
                body="Turn a raw agent capability into a priced outcome and machine-readable acceptance contract."
              />
              <FlowStep
                number="02"
                icon="discovery"
                title="Find demand"
                body="Match only opted-in buyer needs, then make a relevant proposal through OfferRail."
              />
              <FlowStep
                number="03"
                icon="shield"
                title="Negotiate safely"
                body="Accept, counter, or decline inside owner-set price, capacity, chain, and buyer boundaries."
              />
              <FlowStep
                number="04"
                icon="wallet"
                title="Settle & deliver"
                body="Receive Circle USDC, run the seller agent, validate the contract, and issue a receipt."
              />
            </ol>
          </div>
        </section>

        <section className="onboardingSection" id="onboarding">
          <div className="shell">
            <div className="sectionIntro splitIntro">
              <div>
                <span className="eyebrow eyebrowGreen">Seller setup</span>
                <h2>Open for business in four bounded steps.</h2>
              </div>
              <p>
                A product surface, not another chatbot wrapper. Define what the
                agent sells and exactly where it may act without interruption.
              </p>
            </div>
            <Onboarding
              mode={mode}
              backendStatus={backendStatus}
              liveResult={onboarding}
              onActivated={(result) => {
                setOnboarding(result);
                setWorkflow(null);
              }}
            />
          </div>
        </section>

        <section className="operationsSection" id="operations">
          <div className="shell">
            <div className="sectionIntro splitIntro operationsIntro">
              <div>
                <span className="eyebrow eyebrowMint">One order, end to end</span>
                <h2>An autonomous sale you can audit.</h2>
              </div>
              <div className="replayStatus">
                <span
                  className={`replayDot ${
                    mode === "live" && !backendStatus.connected
                      ? "replayDotDisconnected"
                      : ""
                  }`}
                  aria-hidden="true"
                />
                <span>
                  <strong>
                    {mode === "demo"
                      ? "DEMO replay active"
                      : backendStatus.connected
                        ? `LIVE backend · ${backendStatus.mode}`
                        : "LIVE backend disconnected"}
                  </strong>
                  <small>
                    {mode === "demo"
                      ? "Deterministic fixture · movesFunds=false"
                      : `movesFunds=${
                          backendStatus.movesFunds === null
                            ? "unknown"
                            : String(backendStatus.movesFunds)
                        }`}
                  </small>
                </span>
              </div>
            </div>
            {mode === "demo" ? (
              <Workflow />
            ) : backendStatus.connected && onboarding ? (
              <Workflow
                backendStatus={backendStatus}
                onboarding={onboarding}
                liveResult={workflow}
                onCompleted={setWorkflow}
              />
            ) : (
              <DisconnectedState
                title={
                  backendStatus.connected
                    ? "Activate a seller before running a LIVE order."
                    : ownerAuth.authenticated
                      ? "The private API is disconnected."
                      : "Owner login is required."
                }
                body={
                  backendStatus.connected
                    ? "Complete LIVE onboarding above. No static order will be shown in its place."
                    : backendStatus.reason ??
                      "Configure the server-only API connection and retry."
                }
                onRetry={
                  backendStatus.connected ? undefined : refreshLiveAccess
                }
              />
            )}
          </div>
        </section>

        <section className="revenueSection" id="revenue">
          <div className="shell">
            <div className="sectionIntro splitIntro">
              <div>
                <span className="eyebrow eyebrowGreen">Owner console</span>
                <h2>Revenue without a black box.</h2>
              </div>
              <p>
                See what sold, why policy allowed it, whether Circle settled,
                and whether the promised outcome passed validation.
              </p>
            </div>
            {mode === "demo" ? (
              <RevenueDashboard />
            ) : workflow ? (
              <RevenueDashboard liveResult={workflow} />
            ) : (
              <DisconnectedState
                title="No LIVE metrics receipt yet."
                body="Run a connected workflow above. This view will use the backend metrics snapshot and will not substitute demo revenue."
              />
            )}
          </div>
        </section>

        <section className="closingSection">
          <div className="closingOrb closingOrbOne" aria-hidden="true" />
          <div className="closingOrb closingOrbTwo" aria-hidden="true" />
          <div className="shell closingInner">
            <span className="eyebrow eyebrowMint">Your agent can do the work.</span>
            <h2>Now let it earn the work.</h2>
            <p>
              Package one capability, set one safe policy, and inspect the
              commercial loop in explicit DEMO mode or through the private
              server-side LIVE connection.
            </p>
            <a className="button buttonPrimary" href="#onboarding">
              Build a seller profile
              <Icon name="arrow-right" width={18} height={18} />
            </a>
          </div>
        </section>
      </main>

      <footer>
        <div className="shell footerInner">
          <Brand inverse />
          <p>Autonomous offers. Bounded policy. Verifiable delivery.</p>
          <span>DEMO fixtures stay separate from LIVE backend evidence · 2026</span>
        </div>
      </footer>
    </>
  );
}

function ModeBanner({
  mode,
  ownerAuth,
  status,
  onRetry,
}: {
  mode: ProductMode;
  ownerAuth: OwnerAuthStatus;
  status: BackendStatus;
  onRetry: () => void;
}) {
  if (mode === "demo") {
    return (
      <div className="modeBanner modeBannerDemo" role="status">
        <div className="shell">
          <strong>DEMO MODE</strong>
          <span>Static public-safe fixtures · no backend calls · movesFunds=false</span>
        </div>
      </div>
    );
  }

  if (!ownerAuth.authenticated) {
    return (
      <div
        className="modeBanner modeBannerDisconnected"
        role="status"
      >
        <div className="shell">
          <strong>LIVE OWNER LOGIN REQUIRED</strong>
          <span>
            {ownerAuth.reason ??
              "Authenticate before using owner mutation routes"}
          </span>
          <button type="button" onClick={onRetry}>
            Refresh session
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`modeBanner ${
        status.connected ? "modeBannerLive" : "modeBannerDisconnected"
      }`}
      role="status"
    >
      <div className="shell">
        <strong>{status.connected ? "LIVE MODE" : "LIVE DISCONNECTED"}</strong>
        <span>
          backend={status.mode ?? "unknown"} · movesFunds=
          {status.movesFunds === null ? "unknown" : String(status.movesFunds)}
          {status.reason ? ` · ${status.reason}` : ""}
        </span>
        {!status.connected ? (
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </div>
    </div>
  );
}

function OwnerAccessPanel({
  status,
  onLogin,
  onLogout,
}: {
  status: OwnerAuthStatus;
  onLogin: (ownerToken: string) => Promise<void>;
  onLogout: () => Promise<void>;
}) {
  const [ownerToken, setOwnerToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onLogin(ownerToken);
      setOwnerToken("");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Owner login failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    setError(null);
    try {
      await onLogout();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Owner logout failed",
      );
    } finally {
      setBusy(false);
    }
  }

  if (status.authenticated) {
    return (
      <section className="ownerAccess ownerAccessAuthenticated">
        <div className="shell ownerAccessInner">
          <span className="ownerAccessMark">
            <Icon name="lock" width={19} height={19} />
          </span>
          <div>
            <strong>Owner session active</strong>
            <small>
              HttpOnly session expires{" "}
              {status.expiresAt
                ? new Date(status.expiresAt).toLocaleTimeString()
                : "soon"}
            </small>
          </div>
          <button
            className="button buttonQuiet buttonSmall"
            type="button"
            disabled={busy}
            onClick={() => void signOut()}
          >
            {busy ? "Signing out…" : "Log out"}
          </button>
          {error ? <p className="liveError">{error}</p> : null}
        </div>
      </section>
    );
  }

  return (
    <section className="ownerAccess">
      <form className="shell ownerAccessInner" onSubmit={submit}>
        <span className="ownerAccessMark">
          <Icon name="shield" width={20} height={20} />
        </span>
        <div>
          <strong>Authenticate the owner console</strong>
          <small>
            The owner token is exchanged once for a signed, short-lived
            HttpOnly cookie and is not persisted in browser storage.
          </small>
        </div>
        <label>
          <span className="srOnly">Owner token</span>
          <input
            type="password"
            name="ownerToken"
            value={ownerToken}
            autoComplete="current-password"
            placeholder="Owner token"
            disabled={busy || !status.configured}
            onChange={(event) => setOwnerToken(event.target.value)}
          />
        </label>
        <button
          className="button buttonDark buttonSmall"
          type="submit"
          disabled={busy || !status.configured || !ownerToken}
        >
          {busy ? "Authenticating…" : "Owner login"}
        </button>
        {error || !status.configured ? (
          <p className="liveError">
            {error ?? status.reason ?? "Owner authentication is unavailable"}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function FlowStep({
  number,
  icon,
  title,
  body,
}: {
  number: string;
  icon: "sparkles" | "discovery" | "shield" | "wallet";
  title: string;
  body: string;
}) {
  return (
    <li>
      <div className="flowTop">
        <span className="flowIcon">
          <Icon name={icon} width={21} height={21} />
        </span>
        <small>{number}</small>
      </div>
      <h3>{title}</h3>
      <p>{body}</p>
      <span className="flowArrow" aria-hidden="true">
        <Icon name="chevron-right" width={18} height={18} />
      </span>
    </li>
  );
}

function CommerceRailPreview({
  mode,
  status,
  workflow,
}: {
  mode: ProductMode;
  status: BackendStatus;
  workflow: WorkflowResult | null;
}) {
  const isDemo = mode === "demo";
  const amount = isDemo
    ? proposal.finalPriceUsdc
    : workflow?.payment.amountUsdc ?? null;

  return (
    <div className="heroPreview" aria-label="Autonomerce transaction preview">
      <div className="previewGlow" aria-hidden="true" />
      <div className="previewTopbar">
        <span>
          <i />
          Commerce rail
        </span>
        <span className={isDemo || status.connected ? "previewLive" : ""}>
          <i />
          {isDemo ? "DEMO REPLAY" : status.connected ? "LIVE BACKEND" : "DISCONNECTED"}
        </span>
      </div>

      <div className="railStage">
        <div className="railBuyer railActor">
          <span>
            <Icon name="bot" width={18} height={18} />
          </span>
          <div>
            <small>BUYER AGENT</small>
            <strong>
              {isDemo
                ? "GrowthOps"
                : workflow
                  ? new URL(workflow.prospect.buyerAgentUrl).hostname
                  : "Awaiting order"}
            </strong>
          </div>
        </div>

        <div className="railPath railPathOne" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>

        <div className="railCore">
          <span className="railCoreMark">
            <span />
            <span />
            <span />
          </span>
          <small>OFFERRAIL</small>
          <strong>
            {isDemo
              ? "policy passed"
              : !status.connected
                ? "fail closed"
                : workflow
                  ? workflow.receipt.acceptanceVerdict
                  : "backend ready"}
          </strong>
        </div>

        <div className="railPath railPathTwo" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>

        <div className="railSeller railActor">
          <span>
            <Icon name="sparkles" width={18} height={18} />
          </span>
          <div>
            <small>SELLER AGENT</small>
            <strong>{isDemo ? seller.name : "Connected seller"}</strong>
          </div>
        </div>

        <div className="floatingOffer">
          <span>{amount ? "OFFER ACCEPTED" : "NO LIVE RECEIPT"}</span>
          <strong>
            {amount ? `$${formatUsdc(amount)}` : "—"}
            <small> {amount ? "USDC" : ""}</small>
          </strong>
        </div>

        <div className="floatingReceipt">
          <span>
            <Icon name={workflow || isDemo ? "check" : "lock"} width={12} height={12} />
          </span>
          {isDemo
            ? "Static contract delivered"
            : workflow
              ? workflow.receipt.receiptId
              : "No backend receipt yet"}
        </div>
      </div>

      <div className="previewMetrics">
        <div>
          <small>Mode</small>
          <strong>{isDemo ? "DEMO" : status.mode ?? "unknown"}</strong>
        </div>
        <div>
          <small>movesFunds</small>
          <strong>
            {isDemo
              ? "false"
              : status.movesFunds === null
                ? "unknown"
                : String(status.movesFunds)}
          </strong>
        </div>
        <div>
          <small>Receipt</small>
          <strong className={workflow || isDemo ? "greenText" : ""}>
            {isDemo ? "fixture" : workflow ? "backend" : "none"}
          </strong>
        </div>
      </div>
    </div>
  );
}

function DisconnectedState({
  title,
  body,
  onRetry,
}: {
  title: string;
  body: string;
  onRetry?: () => void;
}) {
  return (
    <div className="demoEmpty">
      <span>
        <Icon name="lock" width={24} height={24} />
      </span>
      <h3>{title}</h3>
      <p>{body}</p>
      {onRetry ? (
        <button className="button buttonDark" type="button" onClick={onRetry}>
          Retry private API
          <Icon name="arrow-right" width={17} height={17} />
        </button>
      ) : null}
    </div>
  );
}
