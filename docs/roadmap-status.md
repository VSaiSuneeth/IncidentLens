# IncidentLens Roadmap Status

This repository implements the incident-correlation and observability core. The
statuses below distinguish code present in this repository from work that needs
an external provider, a production environment, or a product decision.

| Phase | Status | Evidence in this repository |
| --- | --- | --- |
| 1. Foundation and planning | Complete | Containerized Python services, Kubernetes manifests, documented SLOs, GitOps configuration, and an architecture decision record. |
| 2. Core dashboard UI | Complete for local demo | A same-origin IncidentLens incident console, Grafana dashboard, and Prometheus recording/alerting rules are included. |
| 3. Incident management | Partial | The correlator persists incidents, exposes list/detail endpoints, updates resolved/reopened lifecycles, stores analyst verdicts, and serves incident evidence/hypotheses in the UI. Assignment, comments, and attachments remain product work. |
| 4. Alert ingestion and correlation | Complete | Alertmanager webhooks, normalization, grouping, deduplication, incident persistence, and alert evidence collection are implemented. |
| 5. AI layer | Partial | Explainable, rule-based hypotheses and confidence scores are implemented. Generative summaries, learned anomaly detection, and clustering need an approved model/data design. |
| 6. Analytics and insights | Partial | Prometheus evidence, SLO status, Grafana visualization, and severity/service information are available. MTTA/MTTR reporting and export workflows need a product-facing reporting layer. |
| 7. Collaboration and notifications | Not started | Authentication, role management, notifications, on-call rotations, and chat integrations require identity and provider configuration. |
| 8. Integrations | Partial | Prometheus, Loki, Tempo, Kubernetes, Argo CD, and Alertmanager are integrated. Vendor-specific cloud monitoring integrations and API-key management are not present. |
| 9. Advanced features | Partial | Runbooks and reproducible chaos scenarios are included. Automated remediation, templates, dependency maps, postmortems, and knowledge-base workflows remain future work. |
| 10. Security and compliance | Partial | Non-root containers, Kubernetes RBAC, and supply-chain CI are included. OAuth/JWT, full RBAC, audit trails, retention policies, and compliance controls require a deployment-specific security design. |
| 11. Performance and scalability | Partial | Container deployment manifests and service monitoring are included. Queueing, caching, multi-tenancy, and load-tested horizontal scaling are not implemented. |
| 12. Testing and QA | Partial | Unit tests, Python compilation, manifest parsing, CI checks, container build/runtime health checks, and deployed UI verification are included. A fresh full alert-to-recovery test is documented but needs a permitted local cluster mutation. |
| 13. Deployment | Partial | Dockerfiles, Kubernetes manifests, GitOps assets, CI workflows, observability configuration, and bootstrap scripts are included. A final production deployment depends on the target cloud/cluster, domains, and secrets. |

## Current verification commands

```powershell
python -m unittest discover -s services/correlator/tests -v
python -m py_compile services/correlator/*.py
docker build -t incidentlens/correlator:verify services/correlator
docker build -t incidentlens/demo-app:verify -f apps/demo-app/Dockerfile apps/demo-app
```

The test suite stubs external observability systems and verifies local evidence
analysis, hypothesis ranking, and SQLite-backed alert deduplication.
