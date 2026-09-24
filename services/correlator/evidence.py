from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

RUNBOOK_BAD_DEPLOYMENT = "/docs/runbooks/bad-deployment.md"
RUNBOOK_DEPENDENCY_SLOWDOWN = "/docs/runbooks/dependency-slowdown.md"


async def prom_query(client: httpx.AsyncClient, base_url: str, query: str) -> dict[str, Any]:
    try:
        response = await client.get(
            f"{base_url}/api/v1/query",
            params={"query": query},
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc), "query": query}


def prom_scalar(result: dict[str, Any]) -> float | None:
    if result.get("status") != "success":
        return None
    data = result.get("data", {})
    if data.get("resultType") != "vector":
        return None
    rows = data.get("result") or []
    if not rows:
        return None
    try:
        return float(rows[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def gather_prometheus_evidence(
    prometheus_url: str,
    service: str,
    namespace: str,
) -> dict[str, Any]:
    window = "5m"
    queries = {
        "error_rate": (
            f'sum(rate(http_requests_total{{namespace="{namespace}", service="{service}", '
            f'handler!="/metrics", status="5xx"}}[{window}])) '
            f"/ clamp_min(sum(rate(http_requests_total{{namespace=\"{namespace}\", "
            f'service="{service}", handler!="/metrics"}}[{window}])), 0.001)'
        ),
        "latency_p95_seconds": (
            f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{'
            f'namespace="{namespace}", service="{service}", handler="/{service}"}}[{window}])))'
        ),
        "request_rate": (
            f'sum(rate(http_requests_total{{namespace="{namespace}", service="{service}", '
            f'handler!="/metrics"}}[{window}]))'
        ),
        "up": f'up{{namespace="{namespace}", service="{service}"}}',
        "pod_restarts": (
            f'sum(kube_pod_container_status_restarts_total{{namespace="{namespace}", '
            f'pod=~"{service}-.*"}})'
        ),
    }

    evidence: dict[str, Any] = {"queries": {}, "values": {}}
    async with httpx.AsyncClient(timeout=10) as client:
        for name, query in queries.items():
            result = await prom_query(client, prometheus_url, query)
            evidence["queries"][name] = query
            evidence["values"][name] = prom_scalar(result) if "error" not in result else result

    return evidence


async def gather_loki_evidence(loki_url: str, namespace: str, service: str | None) -> dict[str, Any]:
    label_filter = f'{{namespace="{namespace}"'
    if service:
        label_filter += f', app="{service}"'
    label_filter += "}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{loki_url}/loki/api/v1/query_range",
                params={"query": label_filter, "limit": 20},
            )
            response.raise_for_status()
            body = response.json()
            excerpts = []
            for stream in body.get("data", {}).get("result", []):
                for _ts, line in stream.get("values", [])[:5]:
                    excerpts.append(line)
            return {"query": label_filter, "excerpts": excerpts, "raw": body}
    except Exception as exc:
        return {"error": str(exc), "query": label_filter}


async def search_tempo_traces(
    tempo_url: str,
    service: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    params = {
        "tags": f"service.name={service}",
        "start": str(int(start.timestamp())),
        "end": str(int(end.timestamp())),
        "limit": 20,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{tempo_url}/api/search", params=params)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        return {"error": str(exc), "params": params}


async def fetch_tempo_trace(tempo_url: str, trace_id: str) -> dict[str, Any]:
    if not trace_id:
        return {"error": "trace_id not provided"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{tempo_url}/api/traces/{trace_id}")
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        return {"error": str(exc), "trace_id": trace_id}


def analyze_trace_spans(trace_payload: dict[str, Any], entry_service: str) -> dict[str, Any]:
    """Summarize per-service span durations for dependency attribution."""
    batches = trace_payload.get("batches") or []
    if not batches and "resourceSpans" in trace_payload:
        batches = [{"resourceSpans": trace_payload["resourceSpans"]}]

    hop_stats: dict[str, dict[str, float]] = {}

    for batch in batches:
        resource_spans = batch.get("resourceSpans") or batch.get("resource_spans") or []
        for rs in resource_spans:
            resource = rs.get("resource", {})
            attrs = {
                a.get("key"): (a.get("value", {}).get("stringValue") or a.get("value"))
                for a in resource.get("attributes", [])
            }
            service_name = attrs.get("service.name") or "unknown"
            for scope_span in rs.get("scopeSpans") or rs.get("scope_spans") or []:
                for span in scope_span.get("spans") or []:
                    name = span.get("name") or "span"
                    start_ns = int(span.get("startTimeUnixNano") or span.get("start_time_unix_nano") or 0)
                    end_ns = int(span.get("endTimeUnixNano") or span.get("end_time_unix_nano") or 0)
                    duration_ms = max(0.0, (end_ns - start_ns) / 1_000_000)
                    key = service_name
                    if key not in hop_stats:
                        hop_stats[key] = {"total_ms": 0.0, "count": 0.0, "max_ms": 0.0}
                    hop_stats[key]["total_ms"] += duration_ms
                    hop_stats[key]["count"] += 1
                    hop_stats[key]["max_ms"] = max(hop_stats[key]["max_ms"], duration_ms)
                    hop_stats[key]["last_span"] = name

    dependency_hops = []
    entry_max = hop_stats.get(entry_service, {}).get("max_ms", 0.0)
    slowest_dep = None
    slowest_ms = 0.0

    for svc, stats in hop_stats.items():
        if svc == entry_service:
            continue
        avg_ms = stats["total_ms"] / max(stats["count"], 1)
        dependency_hops.append(
            {
                "service": svc,
                "avg_ms": round(avg_ms, 2),
                "max_ms": round(stats["max_ms"], 2),
            }
        )
        if stats["max_ms"] > slowest_ms:
            slowest_ms = stats["max_ms"]
            slowest_dep = svc

    dependency_hops.sort(key=lambda h: h["max_ms"], reverse=True)

    return {
        "hop_stats": hop_stats,
        "dependency_hops": dependency_hops,
        "entry_service_max_ms": entry_max,
        "slowest_dependency": slowest_dep,
        "slowest_dependency_max_ms": slowest_ms,
        "entry_service_clean": entry_max < 150 and slowest_ms > max(entry_max * 2, 200),
    }


def deploy_in_incident_window(
    gitops_evidence: dict[str, Any],
    alert_starts_at: str | None,
    window_minutes: int = 30,
) -> bool:
    if not alert_starts_at:
        return False
    try:
        alert_time = datetime.fromisoformat(alert_starts_at.replace("Z", "+00:00"))
    except ValueError:
        return False

    for item in gitops_evidence.get("history") or []:
        deployed_at = item.get("deployed_at") or item.get("deployStartedAt")
        if not deployed_at:
            continue
        try:
            deploy_time = datetime.fromisoformat(deployed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        delta = abs((alert_time - deploy_time).total_seconds())
        if delta <= window_minutes * 60:
            return True
    return False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
