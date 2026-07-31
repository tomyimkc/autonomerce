#!/usr/bin/env bash
set -euo pipefail

chains="${AUTONOMERCE_PAYMENT_ALLOWED_CHAINS:-}"
wallets="${AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS:-}"
binary="${AUTONOMERCE_CIRCLE_CLI_BINARY:-$(command -v circle 2>/dev/null || true)}"
expected_sha256="${AUTONOMERCE_CIRCLE_CLI_SHA256:-}"

if [[ -z "$chains" ]]; then
  echo "BLOCKED: AUTONOMERCE_PAYMENT_ALLOWED_CHAINS is not set."
  exit 2
fi
if [[ -z "$wallets" ]]; then
  echo "BLOCKED: AUTONOMERCE_PAYMENT_ALLOWED_PAYER_WALLETS is not set."
  exit 2
fi
if [[ "$binary" != /* || ! -x "$binary" ]]; then
  echo "BLOCKED: AUTONOMERCE_CIRCLE_CLI_BINARY must be an absolute executable path."
  exit 2
fi
if [[ ! "$expected_sha256" =~ ^[a-f0-9]{64}$ ]]; then
  echo "BLOCKED: AUTONOMERCE_CIRCLE_CLI_SHA256 must be 64 lowercase hex characters."
  exit 2
fi
actual_sha256="$(python3 - "$binary" <<'PY'
import hashlib
from pathlib import Path
import sys

digest = hashlib.sha256()
with Path(sys.argv[1]).open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
)"
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  echo "BLOCKED: Circle CLI SHA-256 does not match the reviewed value."
  exit 2
fi

IFS=',' read -r -a chain_values <<< "$chains"
IFS=',' read -r -a wallet_values <<< "$wallets"
for chain_value in "${chain_values[@]}"; do
  network="$(printf '%s' "$chain_value" | tr '[:lower:]' '[:upper:]' | xargs)"
  case "$network" in
    ARC-TESTNET|BASE-SEPOLIA)
      for wallet_value in "${wallet_values[@]}"; do
        wallet="$(printf '%s' "$wallet_value" | xargs)"
        [[ -n "$wallet" ]] || continue
        "$binary" wallet balance --address "$wallet" --chain "$network" --testnet
      done
      ;;
    BASE)
      for wallet_value in "${wallet_values[@]}"; do
        wallet="$(printf '%s' "$wallet_value" | xargs)"
        [[ -n "$wallet" ]] || continue
        "$binary" wallet balance --address "$wallet" --chain BASE
        echo "Checking mainnet policy for $wallet..."
        "$binary" wallet limit --address "$wallet" --chain BASE
      done
      ;;
    *)
      echo "BLOCKED: unsupported Circle preflight network: $network"
      exit 2
      ;;
  esac
done

echo "CIRCLE PREFLIGHT: PASS (read-only; no payment submitted)"
