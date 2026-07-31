# Private single-node testnet/mainnet deployment

This is the supported durable live-payment shape for the current contest build:

```text
public Next.js web
  -> server-side authenticated proxy
  -> private Compute Engine API VM
  -> persistent disk
  -> SQLite commerce + payment stores
  -> Circle CLI session
```

Cloud Run remains offline-payment-only because the current live stores require
single-node file locking and durable local storage.

The supported live topology uses one SQLite database file for both commerce and
payment tables. Runtime preflight rejects different
`AUTONOMERCE_COMMERCE_SQLITE_PATH` and
`AUTONOMERCE_PAYMENT_SQLITE_PATH` values so startup recovery can reconcile an
externally confirmed payment with proposal state after a process restart. This is a
single-host durability guarantee, not replication or multi-host availability.

## 1. Owner prerequisites

- Google Cloud project and billing;
- least-privilege VM service account;
- IAP or another authenticated private ingress;
- Circle CLI login completed by the owner on the VM;
- strict Circle wallet policy already applied;
- a low-value testnet wallet before mainnet.

## 2. Provision

Example placeholders:

```bash
export PROJECT_ID="your-project"
export ZONE="us-central1-a"
export VM="autonomerce-api"
export DISK="autonomerce-data"
export SERVICE_ACCOUNT="autonomerce-api@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"

gcloud compute disks create "$DISK" \
  --zone "$ZONE" \
  --size 20GB \
  --type pd-balanced

gcloud compute instances create "$VM" \
  --zone "$ZONE" \
  --machine-type e2-small \
  --no-address \
  --service-account "$SERVICE_ACCOUNT" \
  --scopes cloud-platform \
  --boot-disk-size 20GB

gcloud compute instances attach-disk "$VM" \
  --zone "$ZONE" \
  --disk "$DISK"
```

Use IAP for owner administration:

```bash
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap
```

## 3. Persistent disk

On first mount only, identify the attached empty disk before formatting it. Never run
`mkfs` against an existing data disk.

Target mount:

```text
/var/lib/autonomerce
```

Required marker:

```bash
sudo mkdir -p /var/lib/autonomerce
echo AUTONOMERCE_DURABLE_STORE_V1 | \
  sudo tee /var/lib/autonomerce/.autonomerce-durable-volume
sudo chown -R autonomerce:autonomerce /var/lib/autonomerce
sudo chmod 700 /var/lib/autonomerce
```

Configure `/etc/fstab` by disk UUID so the mount survives restart.

## 4. Application environment

Store the environment in:

```text
/etc/autonomerce/autonomerce.env
```

Permissions:

```bash
sudo chown root:autonomerce /etc/autonomerce/autonomerce.env
sudo chmod 640 /etc/autonomerce/autonomerce.env
```

Required testnet shape:

```text
AUTONOMERCE_DEPLOYMENT_MODE=private-single-host-testnet
AUTONOMERCE_MODE=live
AUTONOMERCE_PAYMENT_MODE=testnet
AUTONOMERCE_API_AUTH_MODE=external-auth-proxy
AUTONOMERCE_API_OWNER_ID=<owner-id>
AUTONOMERCE_API_BEARER_TOKEN=<secret-manager-injected>
AUTONOMERCE_TRUSTED_HOSTS=<private-api-hostname>
AUTONOMERCE_API_WORKERS=1
AUTONOMERCE_WEB_PUBLIC_ORIGIN=https://<public-web>
AUTONOMERCE_API_PRIVATE_ORIGIN=https://<private-api>
AUTONOMERCE_GEMINI_MODEL=<stable-gemini-model>
AUTONOMERCE_SELLER_EXECUTOR_FACTORY=autonomerce.sales.executors:build_initial_verification_executor

AUTONOMERCE_PAYMENT_STORE_DURABILITY=single-host-persistent-volume
AUTONOMERCE_PAYMENT_DURABLE_MOUNT_PATH=/var/lib/autonomerce
AUTONOMERCE_PAYMENT_SQLITE_PATH=/var/lib/autonomerce/autonomerce.sqlite3
AUTONOMERCE_COMMERCE_SQLITE_PATH=/var/lib/autonomerce/autonomerce.sqlite3
AUTONOMERCE_PAYMENT_ALLOWED_CHAINS=ARC-TESTNET
AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS=<owner-allowlisted-wallet>
AUTONOMERCE_PAYMENT_ALLOWED_PAYEE_WALLETS=<seller-allowlisted-wallet>
AUTONOMERCE_PAYMENT_MAX_PER_PAYMENT_USDC=1
AUTONOMERCE_PAYMENT_MAX_TOTAL_USDC=10
AUTONOMERCE_PAYMENT_MAX_COUNT=20
AUTONOMERCE_CIRCLE_CLI_BINARY=/usr/local/bin/circle
AUTONOMERCE_CIRCLE_CLI_SHA256=<sha256-of-reviewed-circle-binary>
AUTONOMERCE_TRANSACTION_LOOKUP_FACTORY=<module:function-returning-lookup>
AUTONOMERCE_RECEIPT_PUBLICATION_MODE=verified
AUTONOMERCE_PUBLICATION_CONSENT_VERIFIER_FACTORY=<module:function-returning-verifier>
```

Use Secret Manager or an authenticated bootstrap to inject secrets. Do not place
the real bearer token in an image, startup script, or repository.

`AUTONOMERCE_TRUSTED_HOSTS` contains hostnames, not URLs. Do not use `*` in a
non-offline deployment.

Set `AUTONOMERCE_RECEIPT_PUBLICATION_MODE=disabled` and leave the verifier
factory unset if the pilot will not publish receipts. Preflight rejects ambiguous
or contradictory publication configuration.

## 5. Circle owner login

On the VM, as the service user:

```bash
circle wallet login OWNER_EMAIL --testnet
```

The owner enters the OTP manually. The product does not receive the OTP.

Confirm wallet and balance read-only before starting:

```bash
circle wallet list --type agent --chain ARC-TESTNET --testnet
circle wallet balance \
  --address YOUR_TESTNET_WALLET \
  --chain ARC-TESTNET \
  --testnet
```

## 6. Start

Install the locked Python environment from the checkout:

```bash
cd /opt/autonomerce
uv sync --frozen --extra api --extra gemini
```

Install the systemd unit from `autonomerce-api.service` after replacing the source
checkout path if needed. The checked-in unit uses `/opt/autonomerce`; add a drop-in
so it resolves the locked virtual environment rather than a system `uvicorn`:

```bash
sudo cp infra/compute-engine/autonomerce-api.service \
  /etc/systemd/system/autonomerce-api.service
sudo mkdir -p /etc/systemd/system/autonomerce-api.service.d
printf '%s\n' \
  '[Service]' \
  'Environment="PATH=/opt/autonomerce/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"' \
  | sudo tee /etc/systemd/system/autonomerce-api.service.d/path.conf
sudo systemctl daemon-reload
sudo systemctl enable --now autonomerce-api
sudo systemctl status autonomerce-api
```

The unit runs `infra/start_api.sh`, which runs the fail-closed runtime preflight
before Uvicorn. The script is committed executable and can also be invoked directly
as `./infra/start_api.sh`.

Deploy the public web separately. Its LIVE proxy requires distinct server-only
`AUTONOMERCE_WEB_OWNER_TOKEN`, `AUTONOMERCE_WEB_SESSION_SECRET`, and
`AUTONOMERCE_API_BEARER_TOKEN` values. The browser receives only the signed
short-lived owner-session cookie; do not copy the web owner/session secrets onto the
API VM unless the web server itself runs there.

The API container build uses the committed `uv.lock`, `uv sync --frozen`, and a
digest-pinned Python base image. The live preflight additionally requires the
separately installed Circle CLI's reviewed SHA-256 and the executor rechecks it
before each transfer. This does not provide an SBOM or distribution provenance
attestation.

## 7. Mainnet

Do not convert the testnet VM in place. Create a separately reviewed environment and:

- change deployment/payment mode to mainnet;
- restrict chain to Base;
- use a separately policy-limited mainnet Agent Wallet;
- set the exact `AUTONOMERCE_ENABLE_MAINNET_PAYMENTS` confirmation;
- reduce caps for the first transaction;
- capture owner-approved wallet and policy evidence;
- perform one external low-value transaction;
- stop and inspect receipts before increasing volume.
