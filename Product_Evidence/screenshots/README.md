# Screenshot evidence placeholders and owner checklist

`status: PLACEHOLDER` · `no screenshot files are committed`

No image is generated or represented as captured by this repository change.
The owner must capture, redact, review, and explicitly approve each final image.

| Intended filename | Required visible evidence | Current status | Redaction and truth checks |
|---|---|---|---|
| `01-devpost-registration.png` | joined contest and draft project state | `OWNER INPUT MISSING` | Hide account email, legal profile details, session identifiers, and unrelated projects. |
| `02-cloud-run-deployment.png` | public web URL, API/web revisions, region, and capture time | `OWNER INPUT MISSING` | Hide billing details, principals, tokens, headers, logs, and unrelated services. Match `build-identity.json`. |
| `03-gemini-usage.png` | requested Gemini model and timestamped usage/call context if exposed | `OWNER INPUT MISSING` | Hide prompts, credentials, customer data, billing identifiers, and chain-of-thought. Do not infer served model, tokens, or cost. |
| `04-circle-wallet-policy.png` | Agent Wallet testnet network, public wallets, token, caps, and recipient constraints | `OWNER INPUT MISSING` | Hide OTPs, session tokens, recovery material, internal credentials, and unrelated wallets. Match `wallet-policy.redacted.json`. |
| `05-circle-testnet-explorer.png` | Arc testnet hash, status, canonical USDC, amount, payer, payee, and timestamp | `OWNER INPUT MISSING` | Label `ARC-TESTNET`, `founder-owned`, and `not revenue`. Match the public transaction JSON. |
| `06-no-per-payment-approval-frame.png` | uninterrupted recorded product flow demonstrating the observed no-prompt path | `OWNER INPUT MISSING` | A static empty-dialog screenshot is insufficient; retain video timestamp and policy-before-execution context. |
| `07-public-app.png` | clean-session public application and evidence classification labels | `OWNER INPUT MISSING` | Keep synthetic/testnet labels visible; do not show fixture revenue as business evidence. |
| `08-final-devpost-submission.png` | final submitted project, timestamp, and confirmation | `OWNER INPUT MISSING` | Capture only after legal review and final submit; hide account/private details. |

## Before adding any image

- [ ] source was captured from the intended account/environment;
- [ ] capture time and relevant revision/transaction identifiers are retained;
- [ ] claim wording matches the corresponding JSON artifact;
- [ ] no secret, OTP, recovery material, token, authorization header, private
      customer content, or unrelated account data is visible;
- [ ] filenames and metadata contain no person/customer identity;
- [ ] the image was reviewed at full resolution;
- [ ] the public secret scan passes after addition;
- [ ] the owner approved publication;
- [ ] the archive allowlist was updated intentionally;
- [ ] deterministic archive and manifest verification pass.

Until those checks are complete, keep the screenshot absent and retain this
placeholder rather than fabricating evidence.
