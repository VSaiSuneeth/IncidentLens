import json
import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from kubernetes import client, config
from pydantic import BaseModel

from evidence import (
    analyze_trace_spans,
    deploy_in_incident_window,
    fetch_tempo_trace,
    gather_loki_evidence,
    gather_prometheus_evidence,
    search_tempo_traces,
    utc_now_iso,
)
from hypothesis_engine import rank_hypotheses


app = FastAPI(title="IncidentLens Correlator", version="0.2.0")

DB_PATH = os.getenv("DB_PATH", "incidents.db")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
    if origin.strip()
]
PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://prometheus-kube-prometheus-prometheus.observability.svc.cluster.local:9090",
)
LOKI_URL = os.getenv(
    "LOKI_URL",
    "http://loki-gateway.observability.svc.cluster.local",
)
TEMPO_URL = os.getenv(
    "TEMPO_URL",
    "http://tempo.observability.svc.cluster.local:3200",
)
DEDUP_WINDOW_MINUTES = int(os.getenv("DEDUP_WINDOW_MINUTES", "15"))

if CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-IncidentLens-Token"],
    )

try:
    config.load_incluster_config()
    k8s_core = client.CoreV1Api()
    k8s_apps = client.AppsV1Api()
    k8s_custom = client.CustomObjectsApi()
except Exception:
    k8s_core = None
    k8s_apps = None
    k8s_custom = None


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT UNIQUE NOT NULL,
            incident_group TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            alert_name TEXT,
            severity TEXT,
            service TEXT,
            namespace TEXT,
            payload TEXT NOT NULL,
            evidence TEXT,
            hypotheses TEXT,
            verdict TEXT
        )
        """
    )
    conn.commit()
    _ensure_column(conn, "incidents", "incident_group", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "incidents", "verdict", "TEXT")
    conn.commit()
    conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = {row[1] for row in rows}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


init_db()


class VerdictUpdate(BaseModel):
    verdict: str


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "incidentlens-correlator"}


@app.get("/readyz")
def readyz():
    return {"status": "ready", "database": DB_PATH}


def get_kubernetes_evidence(namespace: str, service: str) -> dict:
    evidence: dict[str, Any] = {"events": [], "pods": [], "deployments": []}
    if not k8s_core:
        return evidence

    try:
        events = k8s_core.list_namespaced_event(namespace=namespace)
        for event in events.items:
            involved = event.involved_object
            message = event.message or ""
            if (
                service.lower() in (involved.name or "").lower()
                or service.lower() in message.lower()
            ):
                evidence["events"].append(
                    {
                        "type": event.type,
                        "reason": event.reason,
                        "message": message,
                        "object": involved.name,
                        "timestamp": str(event.last_timestamp or event.event_time),
                    }
                )

        pods = k8s_core.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app={service}",
        )
        for pod in pods.items:
            container_statuses = pod.status.container_statuses or []
            evidence["pods"].append(
                {
                    "name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "reason": pod.status.reason,
                    "node": pod.spec.node_name,
                    "images": [container.image for container in pod.spec.containers],
                    "ready": all(status.ready for status in container_statuses)
                    if container_statuses
                    else False,
                    "restart_count": sum(status.restart_count for status in container_statuses),
                    "containers": [
                        {
                            "name": status.name,
                            "ready": status.ready,
                            "restart_count": status.restart_count,
                            "state": _container_state(status),
                        }
                        for status in container_statuses
                    ],
                }
            )

        if k8s_apps:
            deployments = k8s_apps.list_namespaced_deployment(
                namespace=namespace,
                label_selector=f"app={service}",
            )
            for deployment in deployments.items:
                evidence["deployments"].append(
                    {
                        "name": deployment.metadata.name,
                        "desired": deployment.spec.replicas,
                        "available": deployment.status.available_replicas or 0,
                        "ready": deployment.status.ready_replicas or 0,
                    }
                )
    except Exception as exc:
        evidence["error"] = str(exc)

    return evidence


def _container_state(status: Any) -> str:
    state = status.state
    for name in ("running", "waiting", "terminated"):
        if getattr(state, name, None) is not None:
            return name
    return "unknown"


def get_gitops_evidence() -> dict:
    if not k8s_custom:
        return {"error": "kubernetes client unavailable", "application": "incidentlens-demo"}

    try:
        application = k8s_custom.get_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace="argocd",
            plural="applications",
            name="incidentlens-demo",
        )
        status = application.get("status", {})
        history = status.get("history", [])
        evidence = {
            "application": "incidentlens-demo",
            "sync_status": status.get("sync", {}).get("status"),
            "current_revision": status.get("sync", {}).get("revision"),
            "health_status": status.get("health", {}).get("status"),
            "history": [],
        }
        for item in history:
            evidence["history"].append(
                {
                    "revision": item.get("revision"),
                    "deployed_at": item.get("deployedAt"),
                    "deploy_started_at": item.get("deployStartedAt"),
                }
            )
        return evidence
    except Exception as exc:
        return {"error": str(exc), "application": "incidentlens-demo"}


async def build_evidence_bundle(
    service: str | None,
    namespace: str,
    alert: dict[str, Any],
) -> dict[str, Any]:
    svc = service or "checkout"
    starts_at = alert.get("startsAt")
    annotations = alert.get("annotations", {})

    prom = await gather_prometheus_evidence(PROMETHEUS_URL, svc, namespace)
    loki = await gather_loki_evidence(LOKI_URL, namespace, service)
    k8s_evidence = get_kubernetes_evidence(namespace, svc) if service else {"events": [], "pods": [], "deployments": []}
    gitops = get_gitops_evidence()

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=15)
    if starts_at:
        try:
            start = datetime.fromisoformat(starts_at.replace("Z", "+00:00")) - timedelta(minutes=5)
        except ValueError:
            pass

    tempo_search = await search_tempo_traces(TEMPO_URL, svc, start, end)
    trace_id = annotations.get("trace_id") or annotations.get("traceID")
    tempo_trace: dict[str, Any] = {}
    tempo_analysis: dict[str, Any] = {}

    if trace_id:
        tempo_trace = await fetch_tempo_trace(TEMPO_URL, trace_id)
    elif tempo_search.get("traces"):
        first = tempo_search["traces"][0]
        trace_id = first.get("traceID") or first.get("traceId")
        if trace_id:
            tempo_trace = await fetch_tempo_trace(TEMPO_URL, trace_id)

    if tempo_trace and "error" not in tempo_trace:
        tempo_analysis = analyze_trace_spans(tempo_trace, svc)

    deploy_flag = deploy_in_incident_window(gitops, starts_at)

    return {
        "collected_at": utc_now_iso(),
        "prometheus": prom,
        "loki": loki,
        "kubernetes": k8s_evidence,
        "gitops": gitops,
        "tempo_search": tempo_search,
        "tempo_trace_id": trace_id,
        "tempo": tempo_trace,
        "tempo_analysis": tempo_analysis,
        "deploy_in_window": deploy_flag,
        "trace_link": f"/explore?trace={trace_id}" if trace_id else None,
    }


def find_open_incident(conn: sqlite3.Connection, incident_group: str) -> sqlite3.Row | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)).isoformat()
    return conn.execute(
        """
        SELECT *
        FROM incidents
        WHERE incident_group = ?
          AND status = 'firing'
          AND updated_at >= ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (incident_group, cutoff),
    ).fetchone()


def find_incident_by_fingerprint(
    conn: sqlite3.Connection,
    fingerprint: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM incidents WHERE fingerprint = ? ORDER BY id DESC LIMIT 1",
        (fingerprint,),
    ).fetchone()


def _verify_webhook_token(request: Request) -> None:
    if not WEBHOOK_TOKEN:
        return
    authorization = request.headers.get("authorization", "")
    supplied = request.headers.get("x-incidentlens-token", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, WEBHOOK_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid IncidentLens webhook token")


async def correlate_alert(payload: dict[str, Any]):
    alerts = payload.get("alerts", [])
    if not alerts:
        raise HTTPException(status_code=400, detail="Alertmanager payload contains no alerts")

    results = []
    conn = get_db()

    for alert in alerts:
        labels = alert.get("labels", {})
        alert_name = labels.get("alertname", "unknown")
        severity = labels.get("severity", "unknown")
        service = labels.get("service")
        namespace = labels.get("namespace", "demo-app")
        fingerprint = alert.get("fingerprint") or f"{alert_name}:{service}:{namespace}:{severity}"
        incident_group = f"{namespace}:{service or 'unknown'}"
        now = utc_now_iso()
        alert_status = str(alert.get("status", "firing")).lower()

        if alert_status == "resolved":
            existing = find_incident_by_fingerprint(conn, fingerprint) or find_open_incident(
                conn,
                incident_group,
            )
            if existing is None:
                results.append(
                    {
                        "incident_id": None,
                        "incident_group": incident_group,
                        "fingerprint": fingerprint,
                        "action": "ignored_resolution",
                    }
                )
                continue

            conn.execute(
                """
                UPDATE incidents
                SET status = ?, updated_at = ?, payload = ?
                WHERE id = ?
                """,
                ("resolved", now, json.dumps(alert), existing["id"]),
            )
            results.append(
                {
                    "incident_id": existing["id"],
                    "incident_group": incident_group,
                    "fingerprint": fingerprint,
                    "action": "resolved",
                }
            )
            continue

        if alert_status != "firing":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported Alertmanager alert status: {alert_status}",
            )

        evidence = await build_evidence_bundle(service, namespace, alert)
        hypotheses = rank_hypotheses(alert_name, service, evidence, alert.get("startsAt"))

        existing = find_open_incident(conn, incident_group)
        if existing:
            conn.execute(
                """
                UPDATE incidents
                SET updated_at = ?, evidence = ?, hypotheses = ?, payload = ?, alert_name = ?
                WHERE id = ?
                """,
                (
                    now,
                    json.dumps(evidence),
                    json.dumps(hypotheses),
                    json.dumps(alert),
                    alert_name,
                    existing["id"],
                ),
            )
            action = "deduplicated"
            row_id = existing["id"]
        else:
            previous = find_incident_by_fingerprint(conn, fingerprint)
            if previous:
                conn.execute(
                    """
                    UPDATE incidents
                    SET incident_group = ?, status = ?, started_at = ?, updated_at = ?,
                        alert_name = ?, severity = ?, service = ?, namespace = ?, payload = ?,
                        evidence = ?, hypotheses = ?, verdict = NULL
                    WHERE id = ?
                    """,
                    (
                        incident_group,
                        "firing",
                        now,
                        now,
                        alert_name,
                        severity,
                        service,
                        namespace,
                        json.dumps(alert),
                        json.dumps(evidence),
                        json.dumps(hypotheses),
                        previous["id"],
                    ),
                )
                action = "reopened"
                row_id = previous["id"]
            else:
                conn.execute(
                    """
                    INSERT INTO incidents (
                        fingerprint, incident_group, status, started_at, updated_at,
                        alert_name, severity, service, namespace, payload, evidence, hypotheses, verdict
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fingerprint,
                        incident_group,
                        "firing",
                        now,
                        now,
                        alert_name,
                        severity,
                        service,
                        namespace,
                        json.dumps(alert),
                        json.dumps(evidence),
                        json.dumps(hypotheses),
                        None,
                    ),
                )
                action = "created"
                row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        results.append(
            {
                "incident_id": row_id,
                "incident_group": incident_group,
                "fingerprint": fingerprint,
                "action": action,
                "top_hypothesis": hypotheses[0] if hypotheses else None,
                "hypotheses": hypotheses,
            }
        )

    conn.commit()
    conn.close()

    return {"status": "success", "results": results}


@app.get("/incidents")
def list_incidents():
    with db_connection() as conn:
        rows = conn.execute("SELECT * FROM incidents ORDER BY id DESC").fetchall()
    return [_row_to_incident(row) for row in rows]


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: int):
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _row_to_incident(row)


@app.patch("/incidents/{incident_id}/verdict")
def set_verdict(incident_id: int, body: VerdictUpdate):
    allowed = {"correct", "incorrect", "unresolved"}
    if body.verdict not in allowed:
        raise HTTPException(status_code=400, detail=f"verdict must be one of {sorted(allowed)}")
    with db_connection() as conn:
        cur = conn.execute(
            "UPDATE incidents SET verdict = ?, updated_at = ? WHERE id = ?",
            (body.verdict, utc_now_iso(), incident_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Incident not found")
    return {"id": incident_id, "verdict": body.verdict}


@app.get("/services/{name}/slo-status")
async def service_slo_status(name: str):
    prom = await gather_prometheus_evidence(PROMETHEUS_URL, name, "demo-app")
    values = prom.get("values", {})
    error_ratio = values.get("error_rate")
    latency_p95 = values.get("latency_p95_seconds")
    availability = None if error_ratio is None else max(0.0, 1.0 - float(error_ratio))
    violating = False
    if error_ratio is not None and float(error_ratio) > 0.01:
        violating = True
    if latency_p95 is not None and float(latency_p95) > 0.3:
        violating = True
    return {
        "service": name,
        "availability_estimate": availability,
        "error_ratio": error_ratio,
        "latency_p95_seconds": latency_p95,
        "slo_violating": violating,
    }


def _row_to_incident(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for field in ("payload", "evidence", "hypotheses"):
        if data.get(field):
            try:
                data[field] = json.loads(data[field])
            except json.JSONDecodeError:
                pass
    return data


@app.post("/webhook/alertmanager")
async def webhook_alertmanager(request: Request):
    _verify_webhook_token(request)
    payload = await request.json()
    return await correlate_alert(payload)


@app.post("/webhook")
async def webhook_legacy(request: Request):
    """Backward-compatible Alertmanager receiver path."""
    _verify_webhook_token(request)
    payload = await request.json()
    return await correlate_alert(payload)


FRONTEND_DIR = Path(__file__).parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="incidentlens-ui")
