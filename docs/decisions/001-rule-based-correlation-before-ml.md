# ADR 001: Rule-based correlation before ML

## Status

Accepted

## Context

IncidentLens must produce explainable incident timelines for interviews and production
adjacent demos. Stakeholders need to trust *why* a hypothesis was ranked, with evidence
that can be audited later.

## Decision

The MVP correlator is a **deterministic rule engine**:

1. Collect evidence from Prometheus, Loki, Tempo, Kubernetes (read-only), and GitOps
   (Argo CD application history).
2. Rank a small set of explicit hypothesis types with confidence scores derived from
   rules, not models.
3. Persist full evidence JSON for every incident.

We intentionally defer ML/LLM root-cause generation until the read-only pipeline and
safety properties (especially dependency attribution) are proven.

## Consequences

- **Pros:** Reproducible demos, defensible interview answers, no cluster mutation
  permissions, easier testing with scripted faults.
- **Cons:** New failure modes need new rules; no semantic log understanding in MVP.
- **Safety:** The dependency-delay scenario must attribute latency to the dependency hop
  and must not recommend remediating the caller (`checkout`) when it is clean.
