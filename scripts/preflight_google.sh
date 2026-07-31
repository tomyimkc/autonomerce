#!/usr/bin/env bash
set -euo pipefail

missing=0

if ! command -v gcloud >/dev/null 2>&1; then
  echo "BLOCKED: gcloud CLI is not installed."
  missing=1
fi

if [[ -z "${GOOGLE_CLOUD_PROJECT:-}" ]]; then
  echo "BLOCKED: GOOGLE_CLOUD_PROJECT is not set."
  missing=1
fi

if [[ "$missing" -ne 0 ]]; then
  exit 2
fi

echo "project=${GOOGLE_CLOUD_PROJECT}"
gcloud auth application-default print-access-token >/dev/null
echo "adc=OK"

for service in aiplatform.googleapis.com run.googleapis.com secretmanager.googleapis.com; do
  if gcloud services list --enabled --project "$GOOGLE_CLOUD_PROJECT" \
      --filter="name:${service}" --format="value(name)" | grep -qx "$service"; then
    echo "${service}=ENABLED"
  else
    echo "${service}=MISSING"
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  exit 2
fi

echo "GOOGLE PREFLIGHT: PASS"
