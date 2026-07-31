#!/usr/bin/env bash
set -euo pipefail

required=(
  GOOGLE_CLOUD_PROJECT
  GOOGLE_CLOUD_REGION
  AUTONOMERCE_API_IMAGE
  AUTONOMERCE_RUNTIME_SERVICE_ACCOUNT
  AUTONOMERCE_ALLOWED_INVOKER
  AUTONOMERCE_API_AUTH_MODE
  AUTONOMERCE_WEB_PUBLIC_ORIGIN
  AUTONOMERCE_API_PRIVATE_ORIGIN
  AUTONOMERCE_TRUSTED_HOSTS
)

for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "BLOCKED: ${name} must be set." >&2
    exit 2
  fi
done

if ! command -v gcloud >/dev/null 2>&1; then
  echo "BLOCKED: gcloud CLI is not installed." >&2
  exit 2
fi

if [[ ! "$AUTONOMERCE_API_IMAGE" =~ @sha256:[0-9a-fA-F]{64}$ ]]; then
  echo "BLOCKED: AUTONOMERCE_API_IMAGE must be an immutable image digest." >&2
  exit 2
fi

if [[ "$AUTONOMERCE_TRUSTED_HOSTS" == *"*"* ||
      "$AUTONOMERCE_TRUSTED_HOSTS" == *"://"* ||
      "$AUTONOMERCE_TRUSTED_HOSTS" == *"/"* ||
      "$AUTONOMERCE_TRUSTED_HOSTS" == *","* ]]; then
  echo "BLOCKED: Cloud Run AUTONOMERCE_TRUSTED_HOSTS must be one explicit hostname." >&2
  exit 2
fi

python3 - "$AUTONOMERCE_API_PRIVATE_ORIGIN" "$AUTONOMERCE_TRUSTED_HOSTS" <<'PY'
from urllib.parse import urlparse
import sys

origin, raw_hosts = sys.argv[1:]
parsed = urlparse(origin)
if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
    print(
        "BLOCKED: AUTONOMERCE_API_PRIVATE_ORIGIN must be an HTTPS origin without a path",
        file=sys.stderr,
    )
    raise SystemExit(2)
hosts = {item.strip().lower() for item in raw_hosts.split(",") if item.strip()}
if parsed.hostname.lower() not in hosts:
    print(
        "BLOCKED: AUTONOMERCE_TRUSTED_HOSTS must include the private API origin host",
        file=sys.stderr,
    )
    raise SystemExit(2)
PY

if [[ "${AUTONOMERCE_PAYMENT_MODE:-offline}" != "offline" ]]; then
  echo "BLOCKED: this Cloud Run deployment path is offline-only." >&2
  echo "The current SQLite adapter does not satisfy Cloud Run durable-store requirements." >&2
  exit 2
fi

if [[ "$AUTONOMERCE_ALLOWED_INVOKER" == "allUsers" ||
      "$AUTONOMERCE_ALLOWED_INVOKER" == "allAuthenticatedUsers" ]]; then
  echo "BLOCKED: public invoker principals are forbidden." >&2
  exit 2
fi

case "$AUTONOMERCE_API_AUTH_MODE" in
  cloud-run-iam)
    ingress="all"
    iap_flag="--no-iap"
    ;;
  iap)
    ingress="all"
    iap_flag="--iap"
    ;;
  service-to-service)
    ingress="internal"
    iap_flag="--no-iap"
    if [[ "$AUTONOMERCE_ALLOWED_INVOKER" != serviceAccount:* ]]; then
      echo "BLOCKED: service-to-service mode requires a serviceAccount invoker." >&2
      exit 2
    fi
    ;;
  *)
    echo "BLOCKED: AUTONOMERCE_API_AUTH_MODE must be cloud-run-iam, iap, or service-to-service." >&2
    exit 2
    ;;
esac

service="${AUTONOMERCE_API_SERVICE:-autonomerce-api}"
location="${GOOGLE_CLOUD_LOCATION:-global}"
model="${AUTONOMERCE_GEMINI_MODEL:-}"

env_vars=(
  "AUTONOMERCE_DEPLOYMENT_MODE=cloud-run-private-offline"
  "AUTONOMERCE_MODE=offline"
  "AUTONOMERCE_API_AUTH_MODE=${AUTONOMERCE_API_AUTH_MODE}"
  "AUTONOMERCE_API_OWNER_ID=${AUTONOMERCE_API_OWNER_ID:-autonomerce-owner}"
  "AUTONOMERCE_WEB_PUBLIC_ORIGIN=${AUTONOMERCE_WEB_PUBLIC_ORIGIN}"
  "AUTONOMERCE_API_PRIVATE_ORIGIN=${AUTONOMERCE_API_PRIVATE_ORIGIN}"
  "AUTONOMERCE_TRUSTED_HOSTS=${AUTONOMERCE_TRUSTED_HOSTS}"
  "AUTONOMERCE_PAYMENT_MODE=offline"
  "AUTONOMERCE_PAYMENT_STORE_DURABILITY=memory-offline"
  "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}"
  "GOOGLE_CLOUD_LOCATION=${location}"
  "GOOGLE_GENAI_USE_VERTEXAI=true"
)
if [[ -n "$model" ]]; then
  env_vars+=("AUTONOMERCE_GEMINI_MODEL=${model}")
fi

env_csv="$(IFS=,; echo "${env_vars[*]}")"

gcloud run deploy "$service" \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$GOOGLE_CLOUD_REGION" \
  --platform managed \
  --image "$AUTONOMERCE_API_IMAGE" \
  --service-account "$AUTONOMERCE_RUNTIME_SERVICE_ACCOUNT" \
  --execution-environment gen2 \
  --port 8080 \
  --concurrency 1 \
  --max-instances 1 \
  --min-instances 0 \
  --ingress "$ingress" \
  --no-allow-unauthenticated \
  "$iap_flag" \
  --set-env-vars "$env_csv" \
  --labels "autonomerce-exposure=private,autonomerce-payment=offline"

gcloud run services add-iam-policy-binding "$service" \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$GOOGLE_CLOUD_REGION" \
  --member "$AUTONOMERCE_ALLOWED_INVOKER" \
  --role roles/run.invoker

policy_json="$(
  gcloud run services get-iam-policy "$service" \
    --project "$GOOGLE_CLOUD_PROJECT" \
    --region "$GOOGLE_CLOUD_REGION" \
    --format json
)"

printf '%s' "$policy_json" | python3 -c '
import json
import os
import sys

policy = json.load(sys.stdin)
expected = os.environ["AUTONOMERCE_ALLOWED_INVOKER"]
public = {"allUsers", "allAuthenticatedUsers"}
members = {
    member
    for binding in policy.get("bindings", [])
    if binding.get("role") == "roles/run.invoker"
    for member in binding.get("members", [])
}
unexpected = sorted(public.intersection(members))
if unexpected:
    raise SystemExit("BLOCKED: public Cloud Run invoker binding detected: " + ", ".join(unexpected))
if expected not in members:
    raise SystemExit("BLOCKED: expected private invoker binding was not found")
print("CLOUD RUN IAM CHECK: PASS (no public invoker binding)")
'

echo "DEPLOYMENT COMPLETE: private offline API only."
echo "Do not enable testnet/mainnet until shared durable storage and application authorization land."
