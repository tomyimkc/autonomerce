# Devpost live-form workbook — Autonomerce

`snapshot: 2026-08-02` · `candidateOnly: true` · `canClaimAGI: false`

This is an owner-review workbook derived from official Devpost MCP read calls.
It is not an API payload, proof of saved answers, permission to submit, or a
substitute for reviewing the live UI and legal attestations.

## 1. Official read boundary

The complete official MCP requirements snapshot generated at
`2026-07-31T23:31:12Z`, together with an August 2 readback, established:

- project ID `1368519`, name `Autonomerce`, slug `autonomerce`;
- project state `published`;
- XPRIZE association `submitted_at: null`;
- project `video_url: null`;
- 36 visible custom fields: 28 required and 8 optional;
- demo video required: **Yes**;
- ZIP required: **Yes**;
- separate website deliverable required: **No**.

The read calls did not expose saved answers, uploads, prize selections, a
submission ID/state, or a project version. Project publication is not
submission confirmation. Do not call `submit_project` merely to save a draft:
without readable saved-answer state, that could omit or overwrite existing
information.

### Readiness

| Status | Meaning |
|---|---|
| `ready_for_owner_review` | Evidence supports the draft, but the owner must compare it with the live form. |
| `blocked_missing_evidence` | A required fact or upload is incomplete; the draft is not final. |
| `blocked_owner_confirmation` | A personal, legal, historical, or forecast fact cannot be inferred from the repository. |
| `owner_only` | The action is an attestation, opt-in, upload, legal decision, or final submit action. |

### Current evidence ceiling

- Repository: `https://github.com/tomyimkc/autonomerce`
- Application:
  `https://autonomerce-web-6dnob6ekdq-uc.a.run.app`
- Deployed AI evidence: one `gemini-2.5-flash` productization call.
- Deployed payment: `offline:mock`
- Deployed fulfillment: `offline:deterministic`
- Funds movement on deployed application: disabled
- Separate Circle proof: one founder-owned `0.10` USDC Agent Wallet transfer
  on Arc testnet with idempotent replay.
- Circle wallet: `0xd5eaf79637decd656e3adb52985cf0afb6cc29d8`
- Explorer:
  `https://testnet.arcscan.app/tx/0xb3a036d46b71e93d37b69ddf1046ff1d708d1c4b33db73b863a4fa3d4a2f7d56`
- Verified external users: `0`
- Paying users: `0`
- Qualifying revenue: `$0.00`
- Related-party revenue: `$0.00`
- Actual total expenses: unknown pending reconciliation
- Profit or margin: not established
- Final video: missing
- Final uploaded Product Evidence ZIP: not established

The founder-owned testnet transfer is not revenue, customer payment, accepted
delivery, mainnet activity, or a deployed Gemini-to-Circle customer order. The
deployed Gemini trace and separate Arc testnet trace must remain separate.

## 2. Required identity, eligibility, and category fields

### `27415` — `What date did you start this project?  (MM-DD-YY)`

- **Type:** required text; format `MM-DD-YY`
- **Proposed answer:** `DRAFT — 07-31-26, only if the owner confirms this is the true first project-development date.`
- **Readiness:** `blocked_owner_confirmation`
- **Evidence:** earliest visible Autonomerce-specific Git history and
  [`../../PREEXISTING-ASSET-DISCLOSURE.md`](../../PREEXISTING-ASSET-DISCLOSURE.md).
- **Blocker:** Git cannot rule out earlier private, local, or uncommitted work.
- **Owner action:** check every private/local source and confirm the first date
  any Autonomerce development occurred.

### `27424` — `Submitter type (individual, team, organization)*`

- **Type/options:** required single-select: `Individual`, `Team`, `Organization`
- **Proposed answer:** `Individual`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** owner-selected entrant structure.
- **Blocker:** saved selection is not exposed.
- **Owner action:** select `Individual` only if no team or organization is being
  represented.

### `27425` — `Country of residence of yourself and team members (if applicable)`

- **Type:** required multi-select country dropdown
- **Proposed answer:** `Hong Kong`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** owner supplied Hong Kong; `Hong Kong` is the exact form option.
- **Blocker:** residence and legal eligibility are owner facts.
- **Owner action:** select the exact option and verify it against the entrant
  profile and rules.

### `27416` — `Which Category are you submitting into?`

- **Type/options:** required single-select:
  `Education & Human Potential`, `Entrepreneurship & Job Creation`,
  `Small Business Services`, `Money & Financial Access`,
  `Professional Services Access`
- **Proposed answer:** `Entrepreneurship & Job Creation`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** locked submission strategy.
- **Blocker:** saved selection is not exposed.
- **Owner action:** select the category and keep the impact narrative limited to
  a path to entrepreneurship, not measured job creation.

## 3. Required AI, business, and viability fields

### `27487` — category impact

- **Exact label:** `Explain how your project uses AI to impact the world, specifically in the category you have chosen.`
- **Type:** required textarea
- **Proposed answer:**

  > Autonomerce targets Entrepreneurship & Job Creation by reducing the
  > repeated commercial work required to turn a useful AI agent into a sellable
  > service. OfferRail converts a declared A2A, MCP, OpenAPI, or custom
  > capability into a structured service SKU, then places proposal,
  > negotiation, settlement, fulfillment, and evidence steps inside explicit
  > owner policy. In the deployed proof, Gemini 2.5 Flash performs adaptive
  > productization while deterministic code retains authority over price,
  > buyer eligibility, wallet, token, network, amount, idempotency, and delivery
  > acceptance. This is intended to let solo builders and small teams
  > commercialize agents without rebuilding a sales and settlement stack for
  > each capability. Current evidence establishes a deployed Gemini
  > productization path and a separate bounded Circle Arc-testnet transfer; it
  > does not establish external customers, revenue, accepted paid delivery, or
  > measured job creation.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** [`DEVPOST-FINAL-CANDIDATE.md`](DEVPOST-FINAL-CANDIDATE.md),
  product README, Gemini receipt, and Circle receipt.
- **Blocker:** no external economic-impact result.
- **Owner action:** preserve the final limitation sentence unless consented
  external evidence replaces it.

### `27482` — business model

- **Exact label:** `Explain the underlying business model of your submission.`
- **Type:** required textarea
- **Proposed answer:**

  > Autonomerce is intended to charge a transaction fee or revenue share only
  > when an agent service is settled and independently accepted, with optional
  > paid onboarding for capability packaging, policy setup, or integration
  > support. The first wedge is a source-verification and evidence-pack service
  > because its input, output, and acceptance criteria can be machine-checked.
  > Longer term, OfferRail is designed as a portable commercial layer for A2A,
  > MCP, OpenAPI, and custom agents. Synthetic, testnet, self-funded, founder,
  > affiliate, reimbursed, and circular activity is excluded from customer
  > revenue. Current qualifying revenue is $0.00.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** final narrative and financial classification schema.
- **Blocker:** pricing, fee percentage, onboarding price, and willingness to pay
  are not validated.
- **Owner action:** confirm the intended first-pilot pricing model.

### `27483` — future operations

- **Exact label:** `How will you sustain business operations in the future?`
- **Type:** required textarea
- **Proposed answer:**

  > The intended operating model is a small self-service platform with
  > usage-linked revenue, optional paid onboarding, deterministic policy gates,
  > and evidence-first support. The near-term plan is to keep one narrow
  > source-verification offer reliable, onboard consented design partners,
  > measure conversion and delivery cost, and expand only after an external
  > order clears payment, fulfillment, acceptance, and evidence gates. Cloud
  > and model costs will be monitored per order, wallet authority will remain
  > capped and allowlisted, and ambiguous payment outcomes will stop for
  > reconciliation. Current operations are not claimed profitable: actual
  > May–August expenses remain unreconciled and qualifying revenue is $0.00.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** deployment, policy, and financial documentation.
- **Blocker:** no validated unit economics, retention, or operating budget.
- **Owner action:** reconcile this answer with the final projections and P&L.

### `27427` — AI tools

- **Exact label:** `Which AI tools have you leveraged while working on this project?`
- **Type:** required textarea
- **Proposed answer:**

  > The deployed application evidence supports Google Gemini 2.5 Flash through
  > the Google Gen AI / Vertex AI path for structured capability
  > productization. AI coding or research assistants used during development
  > should be listed only after the owner confirms the exact products and their
  > actual use; possession of an API key or an implemented adapter is not
  > evidence that a tool was leveraged.

- **Readiness:** `blocked_owner_confirmation`
- **Evidence:** `evidence/public/gemini-call.redacted.json`.
- **Blocker:** the repository cannot establish every development assistant used.
- **Owner action:** append the exact names of AI tools actually used; do not list
  unused providers.

### `27660` — sustainability and viability

- **Exact label:** `Explain how your business model shared above is sustainable and viable.`
- **Type:** required textarea
- **Required topics:** five-year revenue/TAM/market share; path to profitability
  and P&L projections; supporting hypothesis and observed traction
- **Proposed answer:**

  > DRAFT FRAMEWORK — NOT PASTE-READY. In year five, Autonomerce targets
  > owner-confirmed annual revenue of $[TARGET] within an owner-sourced total
  > addressable market of $[TAM], equal to [SHARE]% market share. The model
  > assumes [NUMBER] accepted paid agent-service orders at an average platform
  > fee of $[FEE], plus $[ONBOARDING] of optional onboarding revenue.
  > Profitability is projected for [MONTH/YEAR] when recurring gross profit
  > covers Cloud, Gemini, payment/network, support, tooling, contractor,
  > marketing, and infrastructure costs. The hypothesis is that agent owners
  > will pay or share revenue to avoid rebuilding productization, policy,
  > settlement, fulfillment validation, and evidence infrastructure. Current
  > contest-period traction is reported without extrapolation: zero verified
  > external users, zero paying users, zero qualifying revenue, one deployed
  > Gemini productization receipt, and one separate founder-owned 0.10 USDC
  > Arc-testnet integration transfer.

- **Readiness:** `blocked_owner_confirmation`
- **Evidence:** current technical and financial receipts.
- **Blocker:** no approved TAM source, forecast, pricing assumption, cost model,
  or profitability date.
- **Owner action:** build a bottom-up model, cite its sources, replace every
  bracketed value, and reconcile it with the final P&L.

### `27484` — business operation with AI

- **Exact label:** `Please explain how your business operates with AI.`
- **Type:** required textarea
- **Proposed answer:**

  > Autonomerce separates adaptive reasoning from financial authority. Gemini
  > converts a declared agent capability into a structured service SKU and the
  > codebase exposes advisory seams for relevance, proposal, negotiation, and
  > delivery summaries. Deterministic policy controls scope, price, discount,
  > capacity, buyer eligibility, wallet, token, network, amount, idempotency,
  > settlement confirmation, and delivery acceptance. A seller cannot accept
  > its own output, and payment is not successful delivery. The owner sets
  > authentication, standing policy, wallet funding, emergency stop, customer
  > consent, and publication boundaries.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** architecture, tests, and policy receipt.
- **Blocker:** later AI sales stages are implemented interfaces but are not
  evidenced as deployed decisions.
- **Owner action:** preserve the deployed-versus-implemented distinction.

### `27488` — AI live in production and key decisions

- **Exact label:** `Please explain the extent to which AI is live in production and executes key decisions.`
- **Type:** required textarea
- **Proposed answer:**

  > Gemini 2.5 Flash is live in the deployed private Cloud Run API for one
  > bounded productization decision: transforming a declared
  > source-verification capability into a structured SKU with an outcome, price
  > recommendation, latency, capacity, and acceptance criteria. The receipt
  > identifies the requested model, API revision, timestamp, latency,
  > structured result, and SKU. Owner policy clamps the output. The public
  > deployment does not execute Circle settlement: status reports payment
  > `offline:mock`, fulfillment `offline:deterministic`, and funds movement
  > disabled. The separate Arc testnet transaction is technical Circle
  > evidence, not a deployed Gemini-to-Circle customer order.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** deployment status, build identity, and Gemini receipt.
- **Blocker:** no deployed end-to-end external-customer order.
- **Owner action:** attach observability screenshots and keep the claim limited
  to productization.

### `27485` — Google Cloud product

- **Exact label:** `Please explain which product from Google Cloud you used during the hackathon and how.`
- **Type:** required textarea
- **Proposed answer:**

  > Autonomerce uses Google Cloud Run for a public Next.js
  > backend-for-frontend and a private IAM-protected FastAPI service. Cloud
  > Build produced the deployed revisions. The private API calls Gemini 2.5
  > Flash through the Google Gen AI / Vertex AI integration to productize a
  > declared seller capability. The public status endpoint and redacted build
  > identity identify the deployed service and integration mode. Billing
  > invoices or zero-dollar statements and final observability screenshots are
  > still owner-supplied submission evidence.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** build identity, deployment URL, and Gemini receipt.
- **Blocker:** monthly billing evidence and final observability screenshots.
- **Owner action:** obtain and upload the required redacted evidence.

### `27486` — LLM and Gemini API usage

- **Exact label:** `If your project uses an LLM, it must use Gemini API for at least one LLM call. Please explain which LLMs are used in the project and specifically how the Gemini API is used.`
- **Type:** required textarea
- **Proposed answer:**

  > The deployed application uses Google Gemini 2.5 Flash for structured
  > capability productization. The private Cloud Run API sends a declared
  > source-verification capability to Gemini and receives a structured SKU,
  > including the service outcome, latency, capacity, acceptance criteria, and
  > a price recommendation. Deterministic owner policy validates and clamps the
  > result before it enters the commercial workflow. A redacted deployed-call
  > receipt records the requested model, API revision, timestamp, latency, and
  > structured result. No claim is made that every later proposal,
  > negotiation, payment, or fulfillment decision uses Gemini.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** Gemini receipt and productizer code.
- **Blocker:** final observability upload.
- **Owner action:** compare the model and receipt with the live Cloud console
  immediately before submission.

## 4. Required repository and evidence fields

### `27417` — GitHub repository

- **Exact label:** `URL to your GitHub repo code repository shared with testing@devpost.com and judging@hacker.fund`
- **Type:** required URL
- **Proposed answer:** `https://github.com/tomyimkc/autonomerce`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** public standalone repository.
- **Blocker:** saved value and judge-account access are not exposed.
- **Owner action:** test logged-out access, verify all source is present, and
  confirm access for both listed judge accounts.

### `28104` — product-running evidence upload

- **Exact label:** `Upload evidence of the product running.`
- **Type:** required file
- **Required content:** monthly Cloud billing invoices or zero-dollar
  statements, Gemini observability screenshots, and repository copy in
  `Product_Evidence`
- **Proposed answer:** upload the final owner-reviewed Product Evidence archive
  generated from the exact submitted commit.
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** deterministic archive builder and draft package sources.
- **Blocker:** billing, observability, final screenshots, and upload receipt are
  missing. Current PDFs are marked draft-only.
- **Owner action:** reconcile, redact, regenerate, verify checksum, upload
  manually, and retain a screenshot of the saved upload.

### `27459` — shared-repository confirmation

- **Exact label:** `Shared Repo confirmation`
- **Type:** required checkbox
- **Confirmation:** `I confirm that my GitHub repo linked above is shared with testing@devpost.com and judging@hacker.fund`
- **Proposed answer:** check only after access verification.
- **Readiness:** `owner_only`
- **Evidence:** public repository exists.
- **Blocker:** this is an attestation.
- **Owner action:** verify field `27417`, logged-out access, source completeness,
  and judge access, then personally check the box.

### `27797` — pre-existing resources

- **Exact label:** `Are you using any pre-existing business resources (anything that existed before May 19, 2026) for this Project? If yes: list each pre-existing resource and explain how it’s being applied to the Project.`
- **Type:** required textarea
- **Proposed answer:**

  > Based on tracked repository history, no source resource is currently
  > verified as existing before May 19, 2026. Sophia-AGI materials that predate
  > Autonomerce but appear after that cutoff are nevertheless disclosed:
  > bounded execution budgets, deterministic receipt/redaction patterns,
  > evidence-ledger and audit-chain concepts, task receipts, a Google Gen AI
  > client pattern, and source-discipline modules. Autonomerce's A2A
  > commercialization, OfferRail contracts, Circle settlement binding,
  > product-specific sales lifecycle, and customer evidence model were created
  > during the contest period. This remains subject to owner confirmation of
  > private, local, commercial, or external resources not visible in Git.

- **Readiness:** `blocked_owner_confirmation`
- **Evidence:** pre-existing asset disclosure and
  `Product_Evidence/PRE-MAY-19-RESOURCES.md`.
- **Blocker:** Git cannot establish every private/external resource.
- **Owner action:** inventory pre-May-19 domains, entities, customer lists,
  private code, designs, data, accounts, contracts, and other business assets.

## 5. Required revenue, expense, user, and P&L fields

### `27418` — total revenue

- **Exact label:** `Total Revenue. Total revenue earned during the Hackathon period, in USD (even if $0).`
- **Type:** required number, USD
- **Proposed answer:** `0`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** no qualifying recognized-revenue event.
- **Blocker:** refresh through the final cutoff.
- **Owner action:** reconcile receipts and refunds; keep zero unless a qualifying
  arms-length revenue event passes the evidence gate.

### `27419` — monthly revenue

- **Exact label:** `Revenue by Month. Revenue broken out by calendar month, in USD (even if $0): May, June, July, and August 2026.`
- **Type:** required text, USD
- **Proposed answer:** `May 2026: $0.00; June 2026: $0.00; July 2026: $0.00; August 2026: $0.00 as of the evidence cutoff, subject to final reconciliation.`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** no qualifying event through the current observation time.
- **Blocker:** August remains partial.
- **Owner action:** update the as-of boundary and reconcile every month.

### `27659` — revenue explanation

- **Exact label:** `Explain the revenue shared above.`
- **Type:** required textarea
- **Proposed answer:**

  > Qualifying revenue is $0.00 because no approved evidence establishes an
  > arms-length external-customer payment tied to accepted fulfillment or
  > another documented earned-revenue basis. The deployed workflow uses an
  > offline mock payment. The separate founder-owned 0.10 USDC Arc-testnet
  > transfer is excluded because it is testnet technical evidence, not customer
  > funding or revenue. Synthetic, self, founder, related-party, reimbursed,
  > circular, unsettled, and nonqualifying activity is also excluded. Verified
  > external users and paying users are both zero.

- **Readiness:** `ready_for_owner_review`
- **Evidence:** financial builder and public receipts.
- **Blocker:** final-period reconciliation.
- **Owner action:** regenerate evidence and ensure all revenue/user/P&L values
  reconcile.

### `27423` — related-party revenue

- **Exact label:** `Related-Party Revenue. Any revenue earned during the Hackathon period from team members, family, related entities, or pre-existing customer relationships, in USD (even if $0)..`
- **Source note:** the trailing double period is present in the live Devpost
  label and is retained here for exact field matching.
- **Type:** required textarea, USD
- **Proposed answer:** `$0.00. The founder-owned Arc-testnet transfer is technical test activity and is not recorded as revenue.`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** no approved related-party revenue event.
- **Blocker:** final owner reconciliation.
- **Owner action:** separately disclose any founder, family, affiliate, related
  entity, or pre-existing-customer revenue.

### `27460` — total expenses

- **Exact label:** `Total Expenses. Total costs incurred during the Hackathon period, in USD (even if $0).`
- **Type:** required text, USD
- **Proposed answer:** `DRAFT - verified expense records: $0.00. Actual total expenses remain unknown pending reconciliation of Cloud, Gemini, Circle/network, tooling, compute, contractor, marketing, and infrastructure costs.`
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** no verified expense item; all month completeness states are
  `unknown_total`.
- **Blocker:** a known-item sum of zero is not proof of zero actual expenses.
- **Owner action:** reconcile every eligible invoice, credit, cash payment,
  contractor cost, fee, subscription, and allocated contest expense.

### `27422` — cost of goods sold

- **Exact label:** `Total Cost of Goods Sold during the Hackathon period, in USD (even if $0). Costs directly tied to production of goods and services sold including labor and materials.`
- **Type:** required textarea, USD plus description
- **Proposed answer:** `DRAFT — actual COGS is unknown pending reconciliation. Review per-order Gemini/API use, payment/network fees, fulfillment compute, directly attributable contractor labor, and other per-service costs.`
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** COGS schema exists; no complete ledger.
- **Blocker:** no final amount or allocation rule.
- **Owner action:** classify direct costs consistently and enter the reconciled
  amount plus one-sentence description.

### `27421` — marketing and customer-acquisition expense

- **Exact label:** `Total marketing and customer acquisition expense, in USD (even if $0). This includes advertising and any promotion activities.`
- **Type:** required textarea, USD plus description
- **Proposed answer:** `DRAFT — verified marketing/CAC records: $0.00. Actual marketing and customer-acquisition expense remains unknown pending reconciliation of advertising, promotion, outreach, event, content, and acquisition-tool costs.`
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** no verified marketing item; completeness unknown.
- **Blocker:** absence of supplied receipts is not final zero.
- **Owner action:** reconcile paid and indirect promotion costs and include the
  amount and description in this required field.

### `27465` — users acquired

- **Exact label:** `Number of users acquired during the hackathon (even if 0).`
- **Type:** required text
- **Proposed answer:** `0`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** no consented external-user record.
- **Blocker:** final-period review.
- **Owner action:** exclude founder, synthetic sessions, test agents, CI runs,
  page views, and testnet transfers.

### `27466` — paying users

- **Exact label:** `Number of those users paying for your services or product during the hackathon (even if 0).`
- **Type:** required text
- **Proposed answer:** `0`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** no external user has qualifying positive net revenue.
- **Blocker:** final-period review.
- **Owner action:** count only qualifying external payers after refund and
  revenue-basis checks.

### `27428` — learning level

- **Exact label:** `Describe the level of learning you/your team derived from the project`
- **Type/options:** required single-select: `None`, `Moderate`, `Significant`
- **Proposed answer:** `Significant`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** owner selection and documented payment-authority, idempotency,
  evidence, and deployment lessons.
- **Blocker:** self-assessment.
- **Owner action:** select only if it remains the owner's honest assessment.

### `27672` — P&L upload

- **Exact label:** `Upload your Profit evidence (P&L)`
- **Type:** required file
- **Proposed answer:** upload a final P&L reconciling revenue, COGS,
  marketing/CAC, additional expenses, total expenses, and net P&L.
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** draft generator and PDF exist.
- **Blocker:** actual expenses and net P&L are unknown; current PDF is
  draft-only.
- **Owner action:** complete reconciliation, regenerate, verify every subtotal,
  upload manually, and retain the saved-upload receipt.

## 6. Optional general fields

### `27426` — organization name and EIN

- **Exact label:** `Organization name and Employer Identification Number (if applicable)`
- **Type:** optional text; conditionally relevant for `Organization`
- **Proposed answer:** leave blank for `Individual`.
- **Readiness:** `ready_for_owner_review`
- **Blocker:** none unless submitter type changes.
- **Owner action:** do not supply organization data for an individual entry.

### `27463` — marketing-expense explanation

- **Exact label:** `Please explain the marketing expenses you incurred during the hackathon period, if any.`
- **Type:** optional textarea
- **Proposed answer:** `DRAFT — Marketing/CAC remains blocked because the expense record is incomplete. Verified marketing/CAC items total $0.00, but unknown amounts are not inferred as zero.`
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** returned by the complete official MCP snapshot at
  `2026-07-31T23:31:12Z`; the August 2 required-only summary did not re-enumerate
  ordinary optional fields.
- **Blocker:** actual marketing expense is unreconciled.
- **Owner action:** complete required field `27421` first, then use this only as
  supplementary explanation if still present in the live UI.

### `27464` — additional expenses

- **Exact label:** `Additional Expenses. Please share any missing expenses not covered in the previous expense questions.`
- **Type:** optional text; description requested
- **Proposed answer:** `DRAFT — actual additional expenses are unknown pending reconciliation. Review Cloud, Gemini, Circle/network, tooling, compute, infrastructure, contractor, legal, design, and contest-specific costs not classified as COGS or marketing/CAC.`
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** returned by the complete official MCP snapshot at
  `2026-07-31T23:31:12Z`; not re-enumerated in the August 2 required-only
  summary.
- **Blocker:** no final amount or non-overlapping classification.
- **Owner action:** enter only reconciled costs not already included elsewhere.

### `27470` — public testimonial

- **Exact label:** `Share a verifiable testimonial by a customer or user that is available publicly via a post online.`
- **Type:** optional textarea
- **Proposed answer:** leave blank.
- **Readiness:** `blocked_missing_evidence`
- **Evidence:** no approved external testimonial or public post.
- **Blocker:** testimonials cannot be invented or published without consent.
- **Owner action:** supply a public URL only after a real user posts it and
  separately consents to contest use.

## 7. Optional Circle Agentic Economy Prize fields

### `28108` — Circle prize opt-in

- **Exact label:** `Agentic Economy Prize - Are you opting into the external $50K Agentic Economy Prize`
- **Type/options:** optional single-select: `I confirm`
- **Proposed answer:** `I confirm`
- **Readiness:** `owner_only`
- **Evidence:** owner approved targeting the Circle prize; public testnet proof
  exists.
- **Blocker:** final video and deployed customer-order linkage are incomplete;
  testnet sufficiency is not assumed.
- **Owner action:** recheck sponsor terms and personally opt in if still accurate.

### `28109` — public integration repository

- **Exact label:** `Agentic Economy Prize - A link to a public GitHub repo verifying the integration.`
- **Type:** optional URL; public repository
- **Proposed answer:** `https://github.com/tomyimkc/autonomerce`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** public Circle integration and receipts.
- **Blocker:** saved value and final-commit access are not exposed.
- **Owner action:** verify logged-out access after the final commit.

### `28110` — Circle wallet

- **Exact label:** `Agentic Economy Prize - The agent's Circle wallet address as proof of the transaction.`
- **Type:** optional text
- **Proposed answer:** `0xd5eaf79637decd656e3adb52985cf0afb6cc29d8`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** wallet policy and Arc-testnet receipt.
- **Blocker:** testnet address does not establish customer revenue or deployed
  order linkage.
- **Owner action:** compare character-for-character with Circle history and the
  explorer transaction.

### `28111` — Circle explorer transaction

- **Exact label:** `Agentic Economy Prize - The agent's clickable block-explorer URL as proof of the transaction.`
- **Type:** optional URL
- **Proposed answer:** `https://testnet.arcscan.app/tx/0xb3a036d46b71e93d37b69ddf1046ff1d708d1c4b33db73b863a4fa3d4a2f7d56`
- **Readiness:** `ready_for_owner_review`
- **Evidence:** public receipt and Arc explorer.
- **Blocker:** testnet may not satisfy the sponsor's final interpretation; final
  recorded product demo is missing.
- **Owner action:** open logged out, verify wallet/amount/token/network/hash, and
  preserve the testnet boundary.

## 8. Required non-field deliverables

### Demo video

- **Required:** Yes
- **State:** project `video_url` is null; submission-only attachment not exposed.
- **Blocker:** final public video under three minutes is missing.
- **Owner action:** record one uninterrupted, claim-bounded demo; show deployed
  Gemini productization, explain deployed payment is offline, show the separate
  Arc-testnet proof, test logged-out playback, verify duration, and retain the
  saved-form receipt.

### ZIP

- **Required:** Yes
- **State:** deterministic builder exists; saved upload not exposed.
- **Blocker:** final archive must be regenerated from the exact submitted commit
  after screenshots and financial records are finalized.
- **Owner action:** build, verify, secret-scan, record SHA-256, upload manually,
  and retain the receipt.

### Website

- **Required as separate deliverable:** No
- **State:** public Cloud Run judging deployment exists.
- **Owner action:** keep it reachable and free through judging, verify logged-out
  behavior, and retain the offline demo fallback.

## 9. Final owner-only sequence

1. Confirm field `27415` and the pre-May-19 resource answer.
2. Reconcile every eligible expense and regenerate the final P&L.
3. Replace all bracketed field `27660` projections with sourced figures.
4. Obtain monthly Cloud billing or zero-dollar statements.
5. Capture and redact Gemini observability and product screenshots.
6. Regenerate the Product Evidence archive from the submitted commit.
7. Record and upload the under-three-minute video.
8. Compare every UI answer with this workbook; do not assume saved fields blank.
9. Verify repository access and personally check field `27459`.
10. Review Circle terms and personally decide field `28108`.
11. Review eligibility, identity, privacy, customer consent, and attestations.
12. Submit before `2026-08-17 20:00 UTC` (`2026-08-18 04:00 HKT`).
13. Retain the confirmation page, submitted timestamp, field screenshots,
    upload receipts, final commit SHA, and evidence ZIP checksum.

Until step 13 is complete, describe the project as published on Devpost but not
confirmed submitted to the XPRIZE.
