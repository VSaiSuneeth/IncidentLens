import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence import analyze_trace_spans, deploy_in_incident_window


class EvidenceTests(unittest.TestCase):
    def test_trace_analysis_identifies_a_slow_dependency(self):
        trace = {
            "batches": [
                {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "checkout"},
                                    }
                                ]
                            },
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "name": "GET /checkout",
                                            "startTimeUnixNano": "0",
                                            "endTimeUnixNano": "100000000",
                                        }
                                    ]
                                }
                            ],
                        },
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "inventory"},
                                    }
                                ]
                            },
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "name": "inventory lookup",
                                            "startTimeUnixNano": "0",
                                            "endTimeUnixNano": "650000000",
                                        }
                                    ]
                                }
                            ],
                        },
                    ]
                }
            ]
        }

        analysis = analyze_trace_spans(trace, "checkout")

        self.assertEqual(analysis["slowest_dependency"], "inventory")
        self.assertEqual(analysis["slowest_dependency_max_ms"], 650.0)
        self.assertTrue(analysis["entry_service_clean"])

    def test_deploy_in_window_accepts_iso_timestamps(self):
        alert_time = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
        evidence = {"history": [{"deployed_at": "2026-09-25T09:45:00+00:00"}]}

        self.assertTrue(deploy_in_incident_window(evidence, alert_time.isoformat()))
        self.assertFalse(
            deploy_in_incident_window(
                evidence,
                "2026-09-25T08:00:00+00:00",
            )
        )


if __name__ == "__main__":
    unittest.main()
