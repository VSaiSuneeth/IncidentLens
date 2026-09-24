from __future__ import annotations

from typing import Any

from evidence import RUNBOOK_BAD_DEPLOYMENT, RUNBOOK_DEPENDENCY_SLOWDOWN


def rank_hypotheses(
    alert_name: str,
    service: str | None,
    evidence: dict[str, Any],
    alert_starts_at: str | None,
) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    entry = service or "checkout"

    prom = evidence.get("prometheus", {})
    prom_values = prom.get("values", {}) if isinstance(prom, dict) else {}
    k8s = evidence.get("kubernetes", {}) or {}
    gitops = evidence.get("gitops", {}) or {}
    tempo_analysis = evidence.get("tempo_analysis") or {}

    error_rate = _num(prom_values.get("error_rate"))
    latency_p95 = _num(prom_values.get("latency_p95_seconds"))
    restarts = _num(prom_values.get("pod_restarts"))

    recent_deploy = evidence.get("deploy_in_window", False)
    k8s_restart_events = _has_restart_signal(k8s)
    entry_clean = tempo_analysis.get("entry_service_clean", False)
    slowest_dep = tempo_analysis.get("slowest_dependency")
    slowest_ms = _num(tempo_analysis.get("slowest_dependency_max_ms")) or 0.0

    # Rule: dependency slowdown — do not blame entry service
    if entry_clean and slowest_dep and slowest_dep != entry:
        hypotheses.append(
            {
                "type": "dependency_slowdown",
                "description": (
                    f"Trace evidence shows latency concentrated on dependency '{slowest_dep}' "
                    f"(max {slowest_ms:.0f}ms) while '{entry}' hop remains within normal bounds."
                ),
                "confidence": 0.88,
                "runbook": RUNBOOK_DEPENDENCY_SLOWDOWN,
                "recommended_actions": [
                    f"Investigate and remediate dependency service '{slowest_dep}'.",
                    f"Do not roll back or scale '{entry}' based on this evidence alone.",
                ],
                "explicitly_not_recommended": [f"rollback_{entry}", f"scale_{entry}"],
            }
        )

    # Rule: bad deployment
    if recent_deploy and not entry_clean:
        hypotheses.append(
            {
                "type": "bad_deployment",
                "description": (
                    f"GitOps revision synced within the incident window and metrics/traces "
                    f"implicate '{entry}' (error_rate={error_rate}, p95={latency_p95}s)."
                ),
                "confidence": 0.85,
                "runbook": RUNBOOK_BAD_DEPLOYMENT,
                "recommended_actions": [
                    "Review Argo CD history and revert the recent revision via GitOps.",
                ],
            }
        )
    elif recent_deploy:
        hypotheses.append(
            {
                "type": "bad_deployment",
                "description": (
                    "A GitOps sync occurred near alert time; correlate with metrics before rollback."
                ),
                "confidence": 0.55,
                "runbook": RUNBOOK_BAD_DEPLOYMENT,
                "recommended_actions": ["Compare deploy SHA/timestamp with symptom onset in Grafana."],
            }
        )

    # Rule: pod restart / crash — not a deploy issue
    if (restarts and restarts >= 1) or k8s_restart_events:
        hypotheses.append(
            {
                "type": "pod_restart",
                "description": (
                    f"Elevated restart count ({restarts}) or Kubernetes restart events detected; "
                    "likely infrastructure/lifecycle, not necessarily a bad release."
                ),
                "confidence": 0.72,
                "runbook": RUNBOOK_BAD_DEPLOYMENT,
                "recommended_actions": [
                    "Inspect pod events and logs before attempting a GitOps rollback.",
                ],
            }
        )

    if error_rate is not None and error_rate > 0.05:
        hypotheses.append(
            {
                "type": "error_rate_spike",
                "description": f"Prometheus error rate for {entry} is elevated ({error_rate:.3f}).",
                "confidence": 0.65,
                "runbook": RUNBOOK_BAD_DEPLOYMENT,
            }
        )

    if latency_p95 is not None and latency_p95 > 0.3:
        hypotheses.append(
            {
                "type": "latency_spike",
                "description": f"p95 latency for {entry} exceeds 300ms ({latency_p95:.3f}s).",
                "confidence": 0.60,
                "runbook": RUNBOOK_DEPENDENCY_SLOWDOWN,
            }
        )

    hypotheses.append(
        {
            "type": "alert_trigger",
            "description": f"Alertmanager fired '{alert_name}'.",
            "confidence": 0.15,
        }
    )

    hypotheses.sort(key=lambda h: h.get("confidence", 0), reverse=True)
    return hypotheses


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, dict):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_restart_signal(k8s: dict[str, Any]) -> bool:
    for event in k8s.get("events") or []:
        reason = (event.get("reason") or "").lower()
        message = (event.get("message") or "").lower()
        if any(token in reason for token in ("backoff", "failed", "kill")):
            return True
        if any(token in message for token in ("crashloop", "oom", "back-off")):
            return True
    return False
