# Customer/problem interview template

Use for external prospects, design partners, and customers. Do not backfill,
simulate, or merge multiple people into one record.

## Interview header

- **Private interview ID:** `[interview_...]`
- **UTC date/time:** `[YYYY-MM-DDTHH:MM:SSZ]`
- **Interviewer:** `[name]`
- **Participant relationship:** `[arms-length / prior contact / affiliate / other]`
- **Organization segment:** `[independent agent builder / startup / agency / other]`
- **Role:** `[role]`
- **Geography/time zone:** `[optional]`
- **Recruitment channel:** `[channel]`
- **Compensation:** `[none / amount and form]`
- **Recording permission:** `[yes / no]`
- **Notes permission:** `[yes / no]`
- **Public quote permission:** `[not asked / denied / conditional / granted]`
- **Public identity permission:** `[anonymous / role only / company / full name]`
- **Consent record reference:** `[private path or ID]`

Relationship and compensation do not automatically disqualify an interview, but
they must be disclosed before presenting it as external business evidence.

## Opening script

> Thank you for speaking with me. I am researching how people turn AI-agent
> capabilities into paid services. This is a research interview, not a sales
> commitment. I will ask about your current process before showing any solution.
> You can skip any question or stop at any time.
>
> May I take notes? May I record this conversation? Recording and public quote
> permission are separate; nothing will be published without additional
> permission.

Record the participant’s answers:

- Notes allowed: `[yes/no]`
- Recording allowed: `[yes/no]`
- Continue: `[yes/no]`

## Screener

1. Do you build, own, operate, buy from, or manage AI agents?
2. Has an agent produced an output your organization would pay for?
3. Have you tried to sell an agent capability or buy work from another agent?
4. Who currently approves price, scope, payment, and delivery?
5. Is USDC or another programmable payment rail acceptable in your context?

Do not coach the participant toward the desired answer.

## Problem questions

1. Tell me about the last time you tried to sell or buy an AI-agent-delivered
   service.
2. What triggered the need?
3. What steps occurred from identifying the need to paying and accepting the
   work?
4. Which step required the most human effort?
5. What went wrong or nearly went wrong?
6. How do you decide what the service is worth?
7. How do you bound discounts, scope changes, capacity, or spending?
8. What proof do you need before trusting a payment or a delivered result?
9. What prevents you from allowing an agent to transact without approving each
   payment?
10. What data must never appear in a public receipt?
11. How often does this problem occur?
12. What is the cost of doing nothing or continuing manually?

## Existing alternatives

1. What tools, marketplaces, invoicing, wallets, or manual processes do you use?
2. What do you like about them?
3. What is missing?
4. Have you paid for a workaround? If so, what type and how much? Mark the answer
   private unless separately consented.
5. Who else is involved in the purchase or approval?

## Concept test

Only after the problem interview:

> Autonomerce connects to an existing agent, uses Gemini to recommend sellable
> service SKUs, enforces owner-set commercial and wallet policy in code, lets the
> agent negotiate with opted-in buyers, receives USDC through Circle, validates
> delivery, and issues a redacted receipt.

Ask:

1. What is the first part you would try?
2. What is confusing or unbelievable?
3. Which boundary would you need to control personally?
4. Would you prefer to participate as a seller, buyer, or both?
5. What transaction cap would feel safe for a pilot?
6. Which network/wallet constraints matter?
7. What would make the receipt useful?
8. What would prevent deployment?
9. Would you connect a real agent for a design-partner test?
10. Would you pay for a delivered pilot? If yes, for what outcome and under what
    acceptance contract?

Do not record “would pay” as revenue or a customer. It is purchase intent only.

## Pilot qualification

- Real agent/capability available: `[yes/no]`
- Specific outcome: `[text]`
- Buyer need exists now: `[yes/no]`
- Proposed price range: `[private]`
- Payment rail acceptable: `[yes/no/conditional]`
- Required legal/security review: `[text]`
- Earliest pilot date: `[date]`
- Decision maker identified: `[yes/no]`
- Follow-up agreed: `[yes/no + date]`
- Design partner: `[candidate / accepted / declined]`
- Paying customer: `[no — becomes yes only after external settlement]`

## Quote capture

Write the quote exactly, then obtain separate publication consent.

- Exact quote: `[verbatim]`
- Context: `[question and surrounding meaning]`
- Allowed attribution: `[anonymous / role / company / name]`
- Allowed channels: `[Devpost / video / repository / website]`
- Edits allowed: `[none / grammar only / participant approval required]`
- Expiry or withdrawal terms: `[text]`
- Consent record: `[ID]`

Never paraphrase a quote into stronger support.

## Interview synthesis

- Primary job to be done:
- Current workaround:
- Severity:
- Frequency:
- Buyer:
- User:
- Budget owner:
- Top trust concern:
- Top payment concern:
- Evidence required:
- Strongest disconfirming statement:
- Pilot next step:

## Evidence classification

Choose one:

- `external_problem_interview`
- `external_design_partner`
- `external_paying_customer`
- `affiliate_or_related`
- `founder_internal`
- `invalid_or_withdrawn`

Only the third classification supports paying-customer counts, and only after a
qualifying external payment exists.

## Optional private structured record

```json
{
  "schemaVersion": "autonomerce.customer_interview.private.v1",
  "interviewId": "",
  "occurredAt": "",
  "relationship": "",
  "segment": "",
  "recordingConsent": false,
  "notesConsent": false,
  "publicQuoteConsent": false,
  "classification": "external_problem_interview",
  "problemObserved": "",
  "currentAlternative": "",
  "pilotStatus": "none",
  "consentRecordId": ""
}
```

Keep private identity and consent records outside the public repository.
