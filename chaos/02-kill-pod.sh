#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-demo-app}"
SERVICE="${SERVICE:-checkout}"

POD="$(kubectl get pods -n "${NAMESPACE}" -l "app=${SERVICE}" -o jsonpath='{.items[0].metadata.name}')"
echo "Deleting pod ${POD} in ${NAMESPACE}..."
kubectl delete pod -n "${NAMESPACE}" "${POD}" --wait=false
echo "Expect correlator hypothesis pod_restart (not bad_deployment) after restart alerts/events."
