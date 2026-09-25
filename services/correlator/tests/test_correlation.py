import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

CORRELATOR_DIR = Path(__file__).resolve().parents[1]
TEST_DB_DIR = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = str(Path(TEST_DB_DIR.name) / "incidents.db")
sys.path.insert(0, str(CORRELATOR_DIR))

import main


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        with main.db_connection() as conn:
            conn.execute("DELETE FROM incidents")
            conn.commit()

    def test_repeated_alert_is_deduplicated_into_one_incident(self):
        payload = {
            "alerts": [
                {
                    "fingerprint": "checkout-latency-1",
                    "startsAt": "2026-09-25T10:00:00Z",
                    "labels": {
                        "alertname": "HighLatency",
                        "severity": "critical",
                        "service": "checkout",
                        "namespace": "demo-app",
                    },
                }
            ]
        }
        evidence = {
            "prometheus": {"values": {}},
            "kubernetes": {"events": []},
            "gitops": {},
            "tempo_analysis": {},
            "deploy_in_window": False,
        }

        with patch.object(main, "build_evidence_bundle", AsyncMock(return_value=evidence)):
            created = asyncio.run(main.correlate_alert(payload))
            deduplicated = asyncio.run(main.correlate_alert(payload))

        self.assertEqual(created["results"][0]["action"], "created")
        self.assertEqual(deduplicated["results"][0]["action"], "deduplicated")
        self.assertEqual(len(main.list_incidents()), 1)

    def test_resolved_alert_closes_and_reopens_the_same_incident(self):
        firing = {
            "alerts": [
                {
                    "fingerprint": "checkout-latency-lifecycle",
                    "startsAt": "2026-09-25T10:00:00Z",
                    "status": "firing",
                    "labels": {
                        "alertname": "CheckoutLatencySLOViolation",
                        "severity": "warning",
                        "service": "checkout",
                        "namespace": "demo-app",
                    },
                }
            ]
        }
        resolved = {"alerts": [{**firing["alerts"][0], "status": "resolved"}]}
        evidence = {
            "prometheus": {"values": {}},
            "kubernetes": {"events": []},
            "gitops": {},
            "tempo_analysis": {},
            "deploy_in_window": False,
        }

        with patch.object(main, "build_evidence_bundle", AsyncMock(return_value=evidence)):
            created = asyncio.run(main.correlate_alert(firing))
            closed = asyncio.run(main.correlate_alert(resolved))
            reopened = asyncio.run(main.correlate_alert(firing))

        self.assertEqual(closed["results"][0]["action"], "resolved")
        self.assertEqual(reopened["results"][0]["action"], "reopened")
        self.assertEqual(created["results"][0]["incident_id"], reopened["results"][0]["incident_id"])
        self.assertEqual(main.list_incidents()[0]["status"], "firing")

    def test_incident_console_is_served_with_the_api(self):
        client = TestClient(main.app)

        page = client.get("/")
        script = client.get("/app.js")

        self.assertEqual(page.status_code, 200)
        self.assertIn("IncidentLens", page.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn("loadIncidents", script.text)

    def test_webhook_token_is_enforced_only_when_configured(self):
        client = TestClient(main.app)
        payload = {"alerts": []}

        with patch.object(main, "WEBHOOK_TOKEN", "local-demo-token"):
            rejected = client.post("/webhook/alertmanager", json=payload)
            accepted = client.post(
                "/webhook/alertmanager",
                headers={"X-IncidentLens-Token": "local-demo-token"},
                json=payload,
            )

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 400)


if __name__ == "__main__":
    unittest.main()
