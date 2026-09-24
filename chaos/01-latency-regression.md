# Scenario 1: Latency regression (bad deployment)

Simulates a release that adds latency at the entry service.

## Steps

1. Deploy a checkout image/build with artificial delay (or increase resource limits incorrectly).
2. Generate load: `k6 run scripts/load-test.js`
3. Wait for `CheckoutLatencySLOViolation` or fast burn alert.
4. Verify correlator top hypothesis is `bad_deployment` or `latency_spike` with GitOps revision in evidence.

## Roll back

Revert the GitOps manifest/image tag and sync Argo CD.
