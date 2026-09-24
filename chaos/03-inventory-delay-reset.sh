#!/usr/bin/env bash
set -euo pipefail
kubectl set env deployment/inventory -n "${NAMESPACE:-demo-app}" INVENTORY_DELAY_MS=0
kubectl rollout status deployment/inventory -n "${NAMESPACE:-demo-app}"
echo "Inventory delay disabled."
