# Setup proof checklist

This checklist separates owner-only account actions from publishable proof. Store
raw account screenshots, CLI output, billing details, and consent records in a
private untracked location. Publish only redacted evidence.

## 0. Private OKF record workspace

- [ ] initialize `evidence/private/okf/`;
- [ ] copy and rename the partner, consent, pilot, and authorization templates;
- [ ] store participant identity only through the private identity-vault
      reference;
- [ ] store the microdeal customer input outside tracked files;
- [ ] run `manage_okf_records.py validate`;
- [ ] run `manage_okf_records.py build`;
- [ ] inspect the generated private Home/index pages;
- [ ] keep SQLite under `runtime/sqlite/`;
- [ ] keep full private evidence under `runtime/private-evidence/`;
- [ ] stage the redacted artifact under `publication-staging/`;
- [ ] verify no runtime/staging path is a symlink or tracked project path;
- [ ] bind one authorization to exactly one active pilot;
- [ ] run `pilot-readiness` and retain the no-funds receipt;
- [ ] confirm `readyForExecution` remains false pending fresh owner approval;
- [ ] publish only separately generated `public_redacted` projections.

See [`../../wiki/INDEX.md`](../../wiki/INDEX.md).

## 1. Devpost

Owner-only:

- [ ] legal entrant profile created;
- [ ] contest joined;
- [ ] email/profile verified;
- [ ] participant application completed;
- [ ] draft submission created;
- [ ] main category selected as Entrepreneurship & Job Creation;
- [ ] final legal attestations reviewed;
- [ ] final submit performed before the official deadline.

Private proof:

- [ ] registration screenshot;
- [ ] username and joined date;
- [ ] draft submission ID;
- [ ] organizer clarification records.

Public proof:

- [ ] final project URL;
- [ ] exact submitted text archived;
- [ ] submission timestamp and confirmation.

## 2. Google Cloud

Owner-only:

- [ ] Google Cloud project created;
- [ ] billing linked;
- [ ] required APIs enabled;
- [ ] ADC/workload identity configured;
- [ ] least-privilege IAM reviewed.

Private proof:

- [ ] project number and billing status;
- [ ] authenticated principal;
- [ ] API enablement screenshot/log;
- [ ] budget/alert configuration.

Public redacted proof:

- [ ] project ID if safe to disclose;
- [ ] Cloud Run service URL;
- [ ] deployment region;
- [ ] revision ID;
- [ ] deployed repository commit;
- [ ] `/health` response;
- [ ] deployment timestamp.

## 3. Gemini

- [ ] pinned model configured;
- [ ] deployed application makes the call;
- [ ] call operation is productization, fit, proposal, negotiation, or delivery
      summarization used by the demonstrated order;
- [ ] requested model ID recorded;
- [ ] served model ID recorded if exposed;
- [ ] prompt/config version recorded;
- [ ] UTC timestamp recorded;
- [ ] latency recorded;
- [ ] token usage and cost recorded where available;
- [ ] structured JSON output recorded or hashed;
- [ ] no private chain-of-thought requested or stored;
- [ ] deterministic clamps/overrides recorded;
- [ ] no silent offline/non-Gemini fallback handled the judged order.

Public proof bundle:

- [ ] redacted request metadata;
- [ ] redacted structured output;
- [ ] resulting SKU/proposal/action ID;
- [ ] linkage to deployed revision and order.

## 4. Cloud Run application

- [ ] API deployed from reviewed commit;
- [ ] web app/public demo deployed;
- [ ] HTTPS public URL works in a clean session;
- [ ] health reports intended adapter sources;
- [ ] no credentials appear client-side;
- [ ] logs redact secrets and customer content;
- [ ] rollback revision identified;
- [ ] cold-start and full-order rehearsal completed;
- [ ] availability checked immediately before recording;
- [ ] screenshots include revision/time but no private console data.

## 5. Circle account and Agent Wallet

Owner-only:

- [x] Circle account access complete;
- [ ] OTP/KYC/account verification complete if required;
- [x] correct testnet session active;
- [x] Circle Agent Wallet created;
- [x] owner approves the bounded testnet application policy;
- [ ] mainnet wallet funded only with approved operating budget;
- [ ] emergency stop understood and tested safely.

Private proof:

- [ ] account/wallet creation receipt;
- [ ] raw policy configuration;
- [ ] authentication/session expiry;
- [ ] funding source and budget approval;
- [ ] emergency-stop procedure.

Public redacted proof:

- [x] wallet address;
- [x] network;
- [x] policy ID/version;
- [x] per-transaction cap;
- [x] cumulative/count cap;
- [x] payer/payee or recipient allowlist evidence;
- [x] allowed token and chain;
- [ ] screenshot showing no per-payment approval is required inside policy.

Never publish OTPs, recovery material, session tokens, authorization headers, or
unrestricted API credentials.

## 6. Testnet payment proof

This section records the existing founder-owned Circle integration trace. It is
not the external design-partner pilot and is not customer evidence.

- [x] accepted proposal exists;
- [x] exact amount, chain, token, payer, and payee are authorized;
- [x] durable idempotency store is active for the testnet runner;
- [x] payment confirms;
- [x] explorer and independent Arc RPC confirm;
- [x] same idempotency key does not execute twice;
- [ ] fulfillment follows;
- [ ] delivery validation is separate;
- [x] public record says `testnet`;
- [x] counted-as-revenue is false.

### 6A. External design-partner Arc testnet pilot

- [ ] owner records one arms-length external design partner;
- [ ] participant grants separate pilot, testnet, and publication consent;
- [ ] private customer input contains one to five buyer-supplied claims and
      cited buyer-supplied sources;
- [ ] exact 0.10 USDC Arc testnet authorization record is complete;
- [ ] payer, payee, Circle CLI, interpreter, hashes, and paths are pinned;
- [ ] OKF validation passes;
- [ ] pilot readiness passes without moving funds;
- [ ] owner provides fresh session-specific execution approval;
- [ ] transaction independently confirms;
- [ ] fulfillment is validated separately;
- [ ] public redacted microdeal schema validates;
- [ ] record remains `countedAsRevenue=false` and `payingCustomer=false`.

## 7. External mainnet payment proof

- [ ] customer is external and relationship is documented;
- [ ] customer consent permits the selected public fields;
- [ ] buyer need is opted in;
- [ ] accepted proposal links the order and amount;
- [ ] wallet policy was configured before the transaction;
- [ ] no per-payment approval prompt occurred;
- [ ] Agent Wallet made and/or received the real USDC payment;
- [ ] explorer confirms exact chain, token, amount, payer, and payee;
- [ ] transaction is not self, founder, affiliate, reimbursed, or circular;
- [ ] fulfillment and delivery verdict are linked;
- [ ] refunds/credits are recorded;
- [ ] transaction schema validates;
- [ ] revenue snapshot includes the transaction exactly once.

## 8. Customer proof

- [ ] interview record complete;
- [ ] relationship classification complete;
- [ ] consent record signed/confirmed;
- [ ] public attribution matches selected permission;
- [ ] quote is exact and contextualized;
- [ ] prompt/artifact permissions are separate;
- [ ] order ID is anonymized;
- [ ] identity is absent from metadata and filenames;
- [ ] withdrawal/correction contact exists.

## 9. Revenue and margin proof

- [ ] UTC window fixed;
- [ ] qualifying external transaction list fixed;
- [ ] synthetic/testnet/self/founder/affiliate/reimbursed exclusions enumerated;
- [ ] gross revenue reconciles to transaction records;
- [ ] refunds reconciled;
- [ ] Circle/network fees recorded;
- [ ] Gemini cost recorded;
- [ ] external-service cost recorded;
- [ ] variable compute/infrastructure recorded;
- [ ] gross margin formula recomputed;
- [ ] customer and repeat-purchase denominators documented;
- [ ] revenue JSON validates;
- [ ] dashboard numbers match JSON exactly.

## 10. Public repository

- [ ] standalone repository is public;
- [ ] history and eligibility boundary reviewed;
- [ ] license present;
- [ ] pre-existing asset disclosure present;
- [ ] README and setup instructions work from a clean clone;
- [ ] architecture and threat model present;
- [ ] offline demo is credential-free;
- [ ] testnet instructions are safe;
- [ ] synthetic fixtures are labeled;
- [ ] no path depends on private Sophia files;
- [ ] secret scan passes on files and history;
- [ ] generated caches, `.env`, databases, logs, and private evidence are absent;
- [ ] tagged/released commit matches Devpost.

## 11. Video and final submission

- [ ] final written narrative is 500–1000 words;
- [ ] narrative explains daily AI operation, human responsibilities, economic
      opportunities enabled beyond the founder, and the build story;
- [ ] final live run passes the demo runbook;
- [ ] video runtime below 3:00 after upload;
- [ ] captions complete;
- [ ] Gemini and Circle proof readable;
- [ ] network and evidence classification visible;
- [ ] metrics match public JSON;
- [ ] no unconsented customer data;
- [ ] no secrets in frames, audio, metadata, or subtitles;
- [ ] backup video and checksum retained;
- [ ] every Devpost link tested logged out;
- [ ] official rules reverified on submission day;
- [ ] owner reviews and performs final submit.
