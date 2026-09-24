#!/usr/bin/env bash
set -euo pipefail

SA="system:serviceaccount:observability:incidentlens-correlator"
NS="demo-app"

echo "Expect 'no' for destructive verbs:"
for verb in delete patch create update; do
  for resource in pods deployments; do
    kubectl auth can-i "${verb}" "${resource}" --as="${SA}" -n "${NS}" || true
  done
done

echo "Expect 'yes' for read verbs:"
for verb in get list watch; do
  for resource in pods events deployments; do
    kubectl auth can-i "${verb}" "${resource}" --as="${SA}" -n "${NS}"
  done
done
