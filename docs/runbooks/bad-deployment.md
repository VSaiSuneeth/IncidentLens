# Runbook: Bad deployment

## When this applies

The correlator ranks **bad_deployment** when GitOps/Argo CD shows a revision synced
inside the incident window **and** metrics or traces implicate the affected service's
own spans (not a downstream dependency).

## Steps

1. Confirm the firing alert and open the incident in Grafana or `GET /incidents/{id}`.
2. Compare `evidence.gitops.current_revision` and recent `history` timestamps to alert
   `startsAt`.
3. In Tempo, verify latency/errors concentrate on spans for the deployed service.
4. Roll back via GitOps: revert the image tag or manifest change in the GitOps repo and
   let Argo CD sync (do not hand-patch production without a recorded change).
5. Watch burn-rate alerts clear and error ratio return below SLO thresholds.
6. Record verdict on the incident (`PATCH /incidents/{id}/verdict`).

## Do not

- Delete pods or scale blindly before confirming deploy correlation.
- Blame checkout when trace evidence shows inventory or payment as the slow hop.
