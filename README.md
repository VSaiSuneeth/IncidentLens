# IncidentLens

IncidentLens is a local Kubernetes incident-intelligence demonstration. It
correlates Alertmanager notifications with Prometheus, Loki, Tempo, Kubernetes,
and Argo CD evidence, then exposes ranked, explainable hypotheses and runbooks
through a small incident console.

## Architecture

The [architecture guide](docs/architecture.md) documents the real service,
telemetry, alerting, evidence, persistence, UI, Kubernetes, and CI/CD paths.
It includes the full Mermaid system diagram.

## Features

- Three FastAPI demo services: checkout, payment, and inventory.
- Prometheus ServiceMonitors, recording rules, latency and availability alerts.
- Alertmanager route to the correlator, including resolved notifications.
- Loki, Tempo, OpenTelemetry Collector, Grafana, Kubernetes, and Argo CD
  evidence collection.
- SQLite-backed incident persistence, deduplication, lifecycle resolution and
  reopening, evidence bundles, ranked explainable hypotheses, and runbooks.
- A same-origin incident console served by the correlator at `/`.
- Dockerfiles, Kubernetes manifests, a GitOps application, CI, chaos scripts,
  and automated unit/service tests.

## End-to-End Incident Flow

The verified firing path is:

```text
traffic -> checkout latency degradation -> Prometheus -> Alertmanager ->
IncidentLens correlator -> evidence and hypotheses -> incident console
```

The latency demo uses checkout's real dependency on inventory. A controlled
inventory delay raised checkout p95 latency above the configured SLO, fired
`CheckoutLatencySLOViolation`, reached Alertmanager, and created a correlator
incident with Prometheus, Loki, Kubernetes, Argo CD, and Tempo evidence. See
the [architecture guide](docs/architecture.md#incident-and-recovery-flow) for
the detailed firing and recovery flows.

## Prerequisites

- Docker Desktop, `kind`, `kubectl`, `helm`, and Bash.
- Python 3.11+ for local tests.

## Start a local cluster

```bash
bash scripts/bootstrap-cluster.sh
docker build -t incidentlens/demo-app:dev -f apps/demo-app/Dockerfile apps/demo-app
docker build -t incidentlens/correlator:dev services/correlator
kind load docker-image incidentlens/demo-app:dev --name platform
kind load docker-image incidentlens/correlator:dev --name platform
kubectl apply -f apps/demo-app/k8s/
kubectl apply -f services/correlator/k8s/
kubectl apply -f observability/prometheus/
```

Open the incident console locally:

```bash
kubectl port-forward -n observability svc/incidentlens-correlator 8080:8080
```

Then browse to `http://127.0.0.1:8080/`.

## Local Demo

In one terminal, generate real traffic:

```bash
kubectl run incidentlens-traffic -n demo-app --image=curlimages/curl:8.10.1 \
  --restart=Never --command -- sh -c 'while true; do curl -fsS http://checkout:8000/checkout > /dev/null || true; sleep 0.1; done'
```

In another terminal, inject the reversible inventory delay:

```bash
bash chaos/03-inventory-delay.sh
```

The `CheckoutLatencySLOViolation` rule evaluates every 30 seconds and requires
five minutes above the 300 ms threshold. Once Alertmanager forwards the firing
alert, refresh the IncidentLens console and inspect evidence/hypotheses. Restore
the healthy state and wait for the resolved notification:

```bash
bash chaos/03-inventory-delay-reset.sh
kubectl delete pod -n demo-app incidentlens-traffic --ignore-not-found
```

## Testing

```bash
python -m unittest discover -s services/correlator/tests -v
python -m py_compile services/correlator/*.py services/correlator/tests/*.py
docker build -t incidentlens/correlator:verify services/correlator
docker build -t incidentlens/demo-app:verify -f apps/demo-app/Dockerfile apps/demo-app
bash scripts/verify-e2e.sh
```

## Project Status

- The real firing E2E path is verified.
- Prometheus -> Alertmanager -> Correlator -> Evidence -> UI is verified.
- Recovery and the resolved-notification E2E path remain to be verified.
- Production integrations that require external credentials, including chat,
  cloud monitoring, and production identity providers, remain external.

See the [architecture guide](docs/architecture.md) and
[completion report](docs/completion-report.md) for the evidence, commands, and
remaining limitations.
