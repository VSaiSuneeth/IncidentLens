# Runbook: Dependency slowdown

## When this applies

The correlator ranks **dependency_slowdown** when trace analysis shows elevated duration
on a downstream hop (e.g. `inventory` or `payment`) while the entry service hop remains
within normal bounds.

## Steps

1. Open the incident evidence and review `evidence.tempo_analysis.dependency_hops`.
2. Identify the slowest dependency by span duration — this is the remediation target.
3. Check that hypothesis `recommended_actions` does **not** include changes to checkout
   when checkout spans are clean (safety property).
4. For inventory delays: verify `INVENTORY_DELAY_MS` feature flag / chaos injection is
   not left enabled in production configs.
5. Inspect dependency pods (`kubectl get pods -n demo-app -l app=inventory`) and events
   for scheduling or OOM issues.
6. Mitigate at the dependency: scale inventory/payment, fix network policy, or roll back
   a dependency-only release — not checkout.
7. Record verdict on the incident when resolved.

## Do not

- Roll back checkout or scale checkout when evidence points to a dependency hop.
- Treat a single slow trace as proof — confirm with Prometheus error/latency if present.
