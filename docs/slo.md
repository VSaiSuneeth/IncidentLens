# Demo App Service Level Objectives

These SLOs apply to the **checkout** service (the user-facing entrypoint). Dependency
services (payment, inventory) are measured via traces when attributing incidents.

## Availability

- **Objective:** 99% of `/checkout` requests return a non-5xx response over a rolling
  30-day window.
- **Error budget:** 1% of requests may fail over 30 days.
- **Measurement:** `1 - (5xx rate / total request rate)` from
  `prometheus-fastapi-instrumentator` metrics (`http_requests_total` with
  `status="5xx"`, scoped to `namespace="demo-app"` and `service="checkout"`).

## Latency

- **Objective:** 95% of `/checkout` requests complete in under **300ms**.
- **Measurement:** p95 of `http_request_duration_seconds_bucket` for
  `handler="/checkout"` on the checkout ServiceMonitor target.

## Alerting

Multi-window burn-rate alerts are defined in
`observability/prometheus/incidentlens-rules.yaml`:

| Alert | Window / intent |
|---|---|
| `CheckoutAvailabilityBurnRateFast` | Acute availability breach (~5m burn) |
| `CheckoutAvailabilityBurnRateSlow` | Slow leak (~1h burn) |
| `CheckoutLatencySLOViolation` | p95 latency above 300ms |

Alerts route to the IncidentLens correlator via Alertmanager (`incidentlens` receiver).
