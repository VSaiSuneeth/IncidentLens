import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
import httpx
from fastapi import FastAPI, HTTPException, Request


app = FastAPI(title="IncidentLens Correlator", version="0.1.0")


DB_PATH = os.getenv("DB_PATH", "incidents.db")


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


# Initialize Kubernetes core and apps clients securely
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


def init_db():
    conn = get_db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            alert_name TEXT,
            severity TEXT,
            service TEXT,
            namespace TEXT,
            payload TEXT NOT NULL,
            evidence TEXT,
            hypotheses TEXT
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "service": "incidentlens-correlator",
    }


@app.get("/readyz")
def readyz():
    return {
        "status": "ready",
        "database": DB_PATH,
    }


async def query_prometheus(query: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query},
            )

            response.raise_for_status()
            return response.json()

    except Exception as exc:
        return {
            "error": str(exc),
            "query": query,
        }


async def query_loki(query: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "limit": 20,
                },
            )

            response.raise_for_status()
            return response.json()

    except Exception as exc:
        return {
            "error": str(exc),
            "query": query,
        }


async def query_tempo(trace_id: str) -> dict[str, Any]:
    if not trace_id:
        return {
            "error": "trace_id not provided",
        }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{TEMPO_URL}/api/traces/{trace_id}"
            )

            response.raise_for_status()
            return response.json()

    except Exception as exc:
        return {
            "error": str(exc),
            "trace_id": trace_id,
        }


def get_kubernetes_evidence(
    namespace: str,
    service: str,
) -> dict:
    evidence = {
        "events": [],
        "pods": [],
        "deployments": [],
    }

    if not k8s_core:
        return evidence

    try:
        # ---------------------------------------------------------
        # Kubernetes Events
        # ---------------------------------------------------------
        events = k8s_core.list_namespaced_event(
            namespace=namespace
        )

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
                        "timestamp": str(
                            event.last_timestamp
                            or event.event_time
                        ),
                    }
                )

        # ---------------------------------------------------------
        # Kubernetes Pods
        # ---------------------------------------------------------
        pods = k8s_core.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app={service}",
        )

        for pod in pods.items:
            evidence["pods"].append(
                {
                    "name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "reason": pod.status.reason,
                }
            )

        # ---------------------------------------------------------
        # Kubernetes Deployments
        # ---------------------------------------------------------
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
                        "available": (
                            deployment.status.available_replicas
                            or 0
                        ),
                        "ready": (
                            deployment.status.ready_replicas
                            or 0
                        ),
                    }
                )

    except Exception as exc:
        evidence["error"] = str(exc)

    return evidence


# ================================================================
# GitOps / Argo CD Evidence
# ================================================================
def get_gitops_evidence() -> dict:
    try:
        # Create CustomObjectsApi client
        custom_api = client.CustomObjectsApi()

        # Get Argo CD Application
        application = custom_api.get_namespaced_custom_object(
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
            "current_revision": status.get("sync", {}).get(
                "revision"
            ),
            "health_status": status.get("health", {}).get(
                "status"
            ),
            "history": [],
        }

        for item in history:
            evidence["history"].append(
                {
                    "revision": item.get("revision"),
                    "deployed_at": item.get("deployedAt"),
                    "deploy_started_at": item.get(
                        "deployStartedAt"
                    ),
                }
            )

        return evidence

    except Exception as exc:
        return {
            "error": str(exc),
            "application": "incidentlens-demo",
        }


def build_hypotheses(
    alert_name: str,
    service: str | None,
    evidence: dict[str, Any],
):
    hypotheses = []

    prometheus = evidence.get("prometheus", {})
    loki = evidence.get("loki", {})
    k8s_evidence = evidence.get("kubernetes", {})
    gitops_evidence = evidence.get("gitops", {})

    # -------------------------------------------------------------
    # Prometheus hypothesis
    # -------------------------------------------------------------
    if "error" not in prometheus:
        hypotheses.append(
            {
                "type": "metric_anomaly",
                "description": (
                    f"Prometheus evidence was queried for service "
                    f"{service or 'unknown'}."
                ),
                "confidence": 0.40,
            }
        )

    # -------------------------------------------------------------
    # Loki hypothesis
    # -------------------------------------------------------------
    if "error" not in loki:
        hypotheses.append(
            {
                "type": "log_evidence",
                "description": (
                    f"Loki logs were queried for namespace demo-app "
                    f"and service {service or 'unknown'}."
                ),
                "confidence": 0.30,
            }
        )

    # -------------------------------------------------------------
    # Kubernetes state hypothesis
    # -------------------------------------------------------------
    if k8s_evidence.get("pods"):
        hypotheses.append(
            {
                "type": "k8s_state_analysis",
                "description": (
                    f"Gathered current cluster lifecycle details "
                    f"for {service or 'unknown'}."
                ),
                "confidence": 0.50,
            }
        )

    # -------------------------------------------------------------
    # Kubernetes event hypothesis
    # -------------------------------------------------------------
    if k8s_evidence.get("events"):
        hypotheses.append(
            {
                "type": "kubernetes_event",
                "description": (
                    f"Kubernetes reported "
                    f"{len(k8s_evidence['events'])} "
                    f"event(s) associated with "
                    f"{service or 'unknown'}."
                ),
                "confidence": 0.50,
            }
        )

    # -------------------------------------------------------------
    # GitOps hypothesis
    # -------------------------------------------------------------
    if gitops_evidence and "error" not in gitops_evidence:
        hypotheses.append(
            {
                "type": "gitops_deployment",
                "description": (
                    f"Argo CD application "
                    f"'{gitops_evidence.get('application')}' "
                    f"has sync status "
                    f"'{gitops_evidence.get('sync_status')}' "
                    f"and health status "
                    f"'{gitops_evidence.get('health_status')}'."
                ),
                "confidence": 0.50,
            }
        )

    # -------------------------------------------------------------
    # Alert hypothesis
    # -------------------------------------------------------------
    hypotheses.append(
        {
            "type": "alert_trigger",
            "description": (
                f"Alertmanager reported alert '{alert_name}'."
            ),
            "confidence": 0.20,
        }
    )

    return hypotheses


async def correlate_alert(payload: dict[str, Any]):
    alerts = payload.get("alerts", [])

    if not alerts:
        raise HTTPException(
            status_code=400,
            detail="Alertmanager payload contains no alerts",
        )

    results = []

    for alert in alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        fingerprint = alert.get("fingerprint")
        alert_name = labels.get("alertname", "unknown")
        severity = labels.get("severity", "unknown")
        service = labels.get("service")
        namespace = labels.get("namespace", "demo-app")

        if not fingerprint:
            fingerprint = (
                f"{alert_name}:{service}:{namespace}:{severity}"
            )

        now = datetime.now(timezone.utc).isoformat()

        # ---------------------------------------------------------
        # Prometheus query
        # ---------------------------------------------------------
        prom_query = (
            f'up{{namespace="{namespace}"'
            + (
                f',service="{service}"'
                if service
                else ""
            )
            + "}"
        )

        # ---------------------------------------------------------
        # Loki query
        # ---------------------------------------------------------
        loki_query = (
            f'{{namespace="{namespace}"'
            + (
                f',app="{service}"'
                if service
                else ""
            )
            + "}"
        )

        # ---------------------------------------------------------
        # Collect Prometheus and Loki evidence
        # ---------------------------------------------------------
        evidence = {
            "prometheus": await query_prometheus(
                prom_query
            ),
            "loki": await query_loki(
                loki_query
            ),
        }

        # ---------------------------------------------------------
        # Kubernetes evidence
        # ---------------------------------------------------------
        k8s_evidence = {
            "events": [],
            "pods": [],
            "deployments": [],
        }

        if service:
            k8s_evidence = get_kubernetes_evidence(
                namespace=namespace,
                service=service,
            )

        evidence["kubernetes"] = k8s_evidence

        # ---------------------------------------------------------
        # GitOps / Argo CD evidence
        # ---------------------------------------------------------
        gitops_evidence = get_gitops_evidence()

        evidence["gitops"] = gitops_evidence

        # ---------------------------------------------------------
        # Tempo trace evidence
        # ---------------------------------------------------------
        trace_id = (
            annotations.get("trace_id")
            or annotations.get("traceID")
        )

        if trace_id:
            evidence["tempo"] = await query_tempo(
                trace_id
            )

        # ---------------------------------------------------------
        # Build hypotheses
        # ---------------------------------------------------------
        hypotheses = build_hypotheses(
            alert_name,
            service,
            evidence,
        )

        # ---------------------------------------------------------
        # Incident database handling
        # ---------------------------------------------------------
        conn = get_db()

        existing = conn.execute(
            """
            SELECT id
            FROM incidents
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE incidents
                SET
                    updated_at = ?,
                    evidence = ?,
                    hypotheses = ?,
                    payload = ?
                WHERE fingerprint = ?
                """,
                (
                    now,
                    json.dumps(evidence),
                    json.dumps(hypotheses),
                    json.dumps(alert),
                    fingerprint,
                ),
            )

            action = "updated"

        else:
            conn.execute(
                """
                INSERT INTO incidents (
                    fingerprint,
                    status,
                    started_at,
                    updated_at,
                    alert_name,
                    severity,
                    service,
                    namespace,
                    payload,
                    evidence,
                    hypotheses
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
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
                ),
            )

            action = "created"

        conn.commit()
        conn.close()

        # ---------------------------------------------------------
        # Incident response object
        # ---------------------------------------------------------
        results.append(
            {
                "fingerprint": fingerprint,
                "action": action,

                # Kubernetes evidence
                "kubernetes_evidence": k8s_evidence,

                # GitOps evidence
                "gitops_evidence": gitops_evidence,

                # Generated hypotheses
                "hypotheses": hypotheses,
            }
        )

    return {
        "status": "success",
        "results": results,
    }


# ================================================================
# Incident Retrieval Endpoints
# ================================================================

@app.get("/incidents")
def list_incidents():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT *
            FROM incidents
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT *
            FROM incidents
            WHERE id = ?
            """,
            (incident_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return dict(row)


# ================================================================
# Alertmanager Webhook
# ================================================================

@app.post("/webhook")
async def webhook(request: Request):
    """
    Alertmanager webhook endpoint.
    """
    payload = await request.json()

    return await correlate_alert(payload)