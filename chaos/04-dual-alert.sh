#!/usr/bin/env bash
set -euo pipefail

CORRELATOR_URL="${CORRELATOR_URL:-http://localhost:8080}"
FIXTURE_DIR="$(cd "$(dirname "$0")/.." && pwd)/fixtures"

payload() {
  local fp="$1"
  local alert="$2"
  sed "s/test-checkout-fast-burn/${fp}/g; s/CheckoutAvailabilityBurnRateFast/${alert}/g" \
    "${FIXTURE_DIR}/test-alert.json"
}

curl -sS -X POST "${CORRELATOR_URL}/webhook/alertmanager" \
  -H "Content-Type: application/json" \
  -d "$(payload dual-alert-a CheckoutAvailabilityBurnRateFast)"

curl -sS -X POST "${CORRELATOR_URL}/webhook/alertmanager" \
  -H "Content-Type: application/json" \
  -d "$(payload dual-alert-b CheckoutLatencySLOViolation)"

echo
echo "Check GET ${CORRELATOR_URL}/incidents — related alerts should dedupe into one open incident group demo-app:checkout."
