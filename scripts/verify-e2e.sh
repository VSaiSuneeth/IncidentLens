#!/usr/bin/env bash
# Read-only verification for a running local IncidentLens kind deployment.
set -euo pipefail

PROMETHEUS_NS="${PROMETHEUS_NS:-observability}"
DEMO_NS="${DEMO_NS:-demo-app}"
CORRELATOR_NS="${CORRELATOR_NS:-observability}"
ALERTMANAGER_CONFIG_NS="${ALERTMANAGER_CONFIG_NS:-${DEMO_NS}}"

echo "== Workload health =="
kubectl get pods -n "${DEMO_NS}"
kubectl get pods -n "${CORRELATOR_NS}" -l app=incidentlens-correlator

echo "== Prometheus discovery resources =="
kubectl get servicemonitor -n "${DEMO_NS}"
kubectl get prometheusrule -n "${PROMETHEUS_NS}" incidentlens-slo-rules

echo "== Alertmanager routing =="
kubectl get alertmanagerconfig -n "${ALERTMANAGER_CONFIG_NS}" incidentlens

echo "== Correlator health =="
CORRELATOR_POD="$(kubectl get pod -n "${CORRELATOR_NS}" -l app=incidentlens-correlator -o jsonpath='{.items[0].metadata.name}')"
kubectl exec -n "${CORRELATOR_NS}" "${CORRELATOR_POD}" -- python -c \
  "from urllib.request import urlopen; print(urlopen('http://127.0.0.1:8080/healthz').read().decode())"

echo "== Incident count =="
kubectl exec -n "${CORRELATOR_NS}" "${CORRELATOR_POD}" -- python -c \
  "from urllib.request import urlopen; print(len(__import__('json').loads(urlopen('http://127.0.0.1:8080/incidents').read())))"

echo "Verification completed. For a live incident, follow docs/completion-report.md."
