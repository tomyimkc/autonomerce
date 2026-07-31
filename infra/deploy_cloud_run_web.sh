#!/usr/bin/env bash
set -euo pipefail

blocked() {
  echo "BLOCKED: $*" >&2
  exit 2
}

required=(
  GOOGLE_CLOUD_PROJECT
  GOOGLE_CLOUD_REGION
  AUTONOMERCE_WEB_IMAGE
  AUTONOMERCE_WEB_RUNTIME_SERVICE_ACCOUNT
  AUTONOMERCE_WEB_PUBLIC_ORIGIN
  AUTONOMERCE_WEB_MODE
  AUTONOMERCE_API_IAM_AUTH
)

for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || blocked "${name} must be set."
done

command -v gcloud >/dev/null 2>&1 ||
  blocked "gcloud CLI is not installed."
command -v python3 >/dev/null 2>&1 ||
  blocked "python3 is required for deployment validation."

if [[ ! "$AUTONOMERCE_WEB_IMAGE" =~ ^[^[:space:]@]+@sha256:[0-9a-fA-F]{64}$ ]]; then
  blocked "AUTONOMERCE_WEB_IMAGE must be an immutable image digest."
fi

if [[ ! "$AUTONOMERCE_WEB_RUNTIME_SERVICE_ACCOUNT" =~ ^[a-z0-9][a-z0-9-]{4,28}[a-z0-9]@[a-z0-9][a-z0-9.-]*\.iam\.gserviceaccount\.com$ ]]; then
  blocked "AUTONOMERCE_WEB_RUNTIME_SERVICE_ACCOUNT must be an explicit service-account email."
fi

mode="$(
  printf '%s' "$AUTONOMERCE_WEB_MODE" |
    tr '[:lower:]-' '[:upper:]_'
)"
case "$mode" in
  DEMO)
    ;;
  LIVE | LIVE_BFF)
    mode="LIVE"
    ;;
  *)
    blocked "AUTONOMERCE_WEB_MODE must be explicitly set to DEMO or LIVE."
    ;;
esac

normalize_origin() {
  python3 - "$1" "$2" <<'PY'
import ipaddress
import re
import sys
from urllib.parse import urlparse

name, raw = sys.argv[1:]
try:
    parsed = urlparse(raw)
    port = parsed.port
except ValueError:
    print(f"BLOCKED: {name} is not a valid origin.", file=sys.stderr)
    raise SystemExit(2)

if (
    parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username
    or parsed.password
    or parsed.path not in {"", "/"}
    or parsed.params
    or parsed.query
    or parsed.fragment
):
    print(
        f"BLOCKED: {name} must be a credential-free HTTPS origin without a path.",
        file=sys.stderr,
    )
    raise SystemExit(2)

hostname = parsed.hostname.rstrip(".").lower()
if not hostname or any(character.isspace() for character in hostname):
    print(f"BLOCKED: {name} has an invalid hostname.", file=sys.stderr)
    raise SystemExit(2)

try:
    address = ipaddress.ip_address(hostname)
except ValueError:
    if not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
        hostname,
    ):
        print(f"BLOCKED: {name} has an invalid hostname.", file=sys.stderr)
        raise SystemExit(2)
    display_host = hostname
else:
    display_host = f"[{hostname}]" if address.version == 6 else hostname

default_port = port in {None, 443}
print(f"https://{display_host}" + ("" if default_port else f":{port}"))
PY
}

if ! public_origin="$(
  normalize_origin AUTONOMERCE_WEB_PUBLIC_ORIGIN \
    "$AUTONOMERCE_WEB_PUBLIC_ORIGIN"
)"; then
  exit 2
fi

python3 - "$public_origin" <<'PY'
import ipaddress
import sys
from urllib.parse import urlparse

origin = sys.argv[1]
hostname = urlparse(origin).hostname
if hostname is None or hostname.lower() == "localhost":
    print(
        "BLOCKED: AUTONOMERCE_WEB_PUBLIC_ORIGIN must be a public HTTPS origin.",
        file=sys.stderr,
    )
    raise SystemExit(2)
try:
    address = ipaddress.ip_address(hostname)
except ValueError:
    pass
else:
    if not address.is_global:
        print(
            "BLOCKED: AUTONOMERCE_WEB_PUBLIC_ORIGIN must not use a private or loopback address.",
            file=sys.stderr,
        )
        raise SystemExit(2)
PY

for name in \
  AUTONOMERCE_API_BEARER_TOKEN \
  AUTONOMERCE_API_IAM_ID_TOKEN \
  AUTONOMERCE_WEB_OWNER_TOKEN \
  AUTONOMERCE_WEB_SESSION_SECRET; do
  if [[ -n "${!name:-}" ]]; then
    blocked "${name} must not be passed directly; use a Secret Manager *_SECRET_REF."
  fi
done

while IFS= read -r name; do
  case "$name" in
    NEXT_PUBLIC_*API_BEARER* | \
      NEXT_PUBLIC_*ID_TOKEN* | \
      NEXT_PUBLIC_*SERVERLESS_AUTHORIZATION* | \
      NEXT_PUBLIC_*OWNER_TOKEN* | \
      NEXT_PUBLIC_*SESSION_SECRET*)
      blocked "${name} would expose a server-only credential to browser code."
      ;;
  esac
done < <(compgen -e)

trust_proxy_headers="${AUTONOMERCE_WEB_TRUST_PROXY_HEADERS:-false}"
[[ "$trust_proxy_headers" == "false" ]] ||
  blocked "this direct public Cloud Run path pins AUTONOMERCE_WEB_TRUST_PROXY_HEADERS=false."

allow_moves_funds="${AUTONOMERCE_ALLOW_MOVES_FUNDS:-false}"
case "$allow_moves_funds" in
  true | false)
    ;;
  *)
    blocked "AUTONOMERCE_ALLOW_MOVES_FUNDS must be exactly true or false."
    ;;
esac

service="${AUTONOMERCE_WEB_SERVICE:-autonomerce-web}"
env_vars=(
  "NODE_ENV=production"
  "AUTONOMERCE_WEB_MODE=${mode}"
  "AUTONOMERCE_WEB_PUBLIC_ORIGIN=${public_origin}"
  "AUTONOMERCE_WEB_TRUST_PROXY_HEADERS=false"
)
deploy_shape_args=()
secret_args=()
web_labels=""

case "$mode" in
  DEMO)
    [[ "$allow_moves_funds" == "false" ]] ||
      blocked "DEMO mode cannot enable funds movement."
    [[ "$AUTONOMERCE_API_IAM_AUTH" == "false" ]] ||
      blocked "DEMO mode requires AUTONOMERCE_API_IAM_AUTH=false."

    for name in \
      AUTONOMERCE_API_BASE_URL \
      AUTONOMERCE_API_PRIVATE_ORIGIN \
      AUTONOMERCE_API_IAM_AUDIENCE \
      AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF \
      AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF \
      AUTONOMERCE_WEB_SESSION_SECRET_REF; do
      if [[ -n "${!name:-}" ]]; then
        blocked "DEMO mode is synthetic/no-backend; unset ${name}."
      fi
    done

    env_vars+=(
      "AUTONOMERCE_WEB_DEPLOYMENT_MODE=cloud-run-public-demo"
      "AUTONOMERCE_DEMO_SYNTHETIC_ONLY=true"
      "AUTONOMERCE_ALLOW_MOVES_FUNDS=false"
      "AUTONOMERCE_API_IAM_AUTH=false"
    )
    deploy_shape_args=(
      --concurrency 40
      --max 3
      --max-instances 3
    )
    secret_args=(--clear-secrets)
    web_labels="autonomerce-exposure=public,autonomerce-web-mode=demo,autonomerce-mode=demo,autonomerce-payment=offline"
    ;;
  LIVE)
    [[ -n "${AUTONOMERCE_API_PRIVATE_ORIGIN:-}" ]] ||
      blocked "LIVE mode requires AUTONOMERCE_API_PRIVATE_ORIGIN."

    if ! private_origin="$(
      normalize_origin AUTONOMERCE_API_PRIVATE_ORIGIN \
        "$AUTONOMERCE_API_PRIVATE_ORIGIN"
    )"; then
      exit 2
    fi
    [[ "$private_origin" != "$public_origin" ]] ||
      blocked "LIVE public web and private API origins must be different."

    case "$AUTONOMERCE_API_IAM_AUTH" in
      true)
        [[ -n "${AUTONOMERCE_API_IAM_AUDIENCE:-}" ]] ||
          blocked "LIVE IAM auth requires AUTONOMERCE_API_IAM_AUDIENCE."
        if ! iam_audience="$(
          normalize_origin AUTONOMERCE_API_IAM_AUDIENCE \
            "$AUTONOMERCE_API_IAM_AUDIENCE"
        )"; then
          exit 2
        fi
        [[ "$iam_audience" == "$private_origin" ]] ||
          blocked "AUTONOMERCE_API_IAM_AUDIENCE must match AUTONOMERCE_API_PRIVATE_ORIGIN."
        ;;
      false)
        [[ -z "${AUTONOMERCE_API_IAM_AUDIENCE:-}" ]] ||
          blocked "AUTONOMERCE_API_IAM_AUDIENCE must be unset when IAM auth is disabled."
        ;;
      *)
        blocked "AUTONOMERCE_API_IAM_AUTH must be exactly true or false."
        ;;
    esac

    secret_names=(
      AUTONOMERCE_API_BEARER_TOKEN_SECRET_REF
      AUTONOMERCE_WEB_OWNER_TOKEN_SECRET_REF
      AUTONOMERCE_WEB_SESSION_SECRET_REF
    )
    secret_refs=()
    for name in "${secret_names[@]}"; do
      [[ -n "${!name:-}" ]] ||
        blocked "LIVE mode requires ${name}."
      secret_refs+=("${!name}")
    done

    for ref in "${secret_refs[@]}"; do
      if [[ ! "$ref" =~ ^([A-Za-z0-9_-]+|projects/[A-Za-z0-9._:-]+/secrets/[A-Za-z0-9_-]+):[1-9][0-9]*$ ]]; then
        blocked "LIVE Secret Manager references must name an explicit numeric secret version."
      fi
    done

    api_secret_id="${secret_refs[0]%:*}"
    owner_secret_id="${secret_refs[1]%:*}"
    session_secret_id="${secret_refs[2]%:*}"
    if [[ "$api_secret_id" == "$owner_secret_id" ||
          "$api_secret_id" == "$session_secret_id" ||
          "$owner_secret_id" == "$session_secret_id" ]]; then
      blocked "LIVE API bearer, owner token, and session signing secret must use three distinct secrets."
    fi

    if [[ -n "${AUTONOMERCE_API_BASE_URL:-}" ]]; then
      if ! base_url="$(
        normalize_origin AUTONOMERCE_API_BASE_URL "$AUTONOMERCE_API_BASE_URL"
      )"; then
        exit 2
      fi
      [[ "$base_url" == "$private_origin" ]] ||
        blocked "AUTONOMERCE_API_BASE_URL conflicts with AUTONOMERCE_API_PRIVATE_ORIGIN."
    fi

    env_vars+=(
      "AUTONOMERCE_WEB_DEPLOYMENT_MODE=cloud-run-public-live-bff"
      "AUTONOMERCE_API_PRIVATE_ORIGIN=${private_origin}"
      "AUTONOMERCE_ALLOW_MOVES_FUNDS=${allow_moves_funds}"
      "AUTONOMERCE_API_IAM_AUTH=${AUTONOMERCE_API_IAM_AUTH}"
    )
    if [[ "$AUTONOMERCE_API_IAM_AUTH" == "true" ]]; then
      env_vars+=("AUTONOMERCE_API_IAM_AUDIENCE=${iam_audience}")
    fi
    deploy_shape_args=(
      --concurrency 1
      --max 1
      --max-instances 1
    )
    secret_args=(
      --set-secrets
      "AUTONOMERCE_API_BEARER_TOKEN=${secret_refs[0]},AUTONOMERCE_WEB_OWNER_TOKEN=${secret_refs[1]},AUTONOMERCE_WEB_SESSION_SECRET=${secret_refs[2]}"
    )
    web_labels="autonomerce-exposure=public,autonomerce-web-mode=live,autonomerce-mode=live-bff,autonomerce-payment=offline"
    ;;
esac

env_csv="$(IFS=,; printf '%s' "${env_vars[*]}")"

gcloud run deploy "$service" \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$GOOGLE_CLOUD_REGION" \
  --platform managed \
  --image "$AUTONOMERCE_WEB_IMAGE" \
  --service-account "$AUTONOMERCE_WEB_RUNTIME_SERVICE_ACCOUNT" \
  --execution-environment gen2 \
  --port 8080 \
  --cpu 1 \
  --memory 512Mi \
  --timeout 240s \
  --min-instances 0 \
  --ingress all \
  --allow-unauthenticated \
  --invoker-iam-check \
  --no-iap \
  --no-session-affinity \
  "${deploy_shape_args[@]}" \
  --set-env-vars "$env_csv" \
  "${secret_args[@]}" \
  --labels "$web_labels"

echo "DEPLOYMENT COMPLETE: public web mode=${mode}, origin=${public_origin}."
if [[ "$mode" == "DEMO" ]]; then
  echo "DEMO is synthetic, has no private backend configuration, and cannot move funds."
else
  echo "LIVE uses a server-side private API origin and Secret Manager credentials."
  echo "Cloud Run IAM authentication enabled: ${AUTONOMERCE_API_IAM_AUTH}."
  echo "Funds movement enabled: ${allow_moves_funds}."
fi
