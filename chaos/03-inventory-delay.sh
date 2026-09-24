#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-demo-app}"
DELAY_MS="${INVENTORY_DELAY_MS:-800}"

kubectl set env deployment/inventory -n "${NAMESPACE}" INVENTORY_DELAY_MS="${DELAY_MS}"
kubectl rollout status deployment/inventory -n "${NAMESPACE}"

echo "Inventory delay set to ${DELAY_MS}ms. Run load test and verify dependency_slowdown attributes fault to inventory, not checkout."
