import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypothesis_engine import rank_hypotheses


class HypothesisEngineTests(unittest.TestCase):
    def test_dependency_evidence_prevents_entry_service_rollback(self):
        evidence = {
            "prometheus": {"values": {"error_rate": 0.03, "latency_p95_seconds": 0.7}},
            "kubernetes": {"events": []},
            "gitops": {},
            "deploy_in_window": False,
            "tempo_analysis": {
                "entry_service_clean": True,
                "slowest_dependency": "inventory",
                "slowest_dependency_max_ms": 820,
            },
        }

        hypotheses = rank_hypotheses("HighLatency", "checkout", evidence, None)

        primary = hypotheses[0]
        self.assertEqual(primary["type"], "dependency_slowdown")
        self.assertIn("rollback_checkout", primary["explicitly_not_recommended"])
        self.assertIn("inventory", primary["recommended_actions"][0])

    def test_recent_deployment_with_entry_service_signal_is_ranked(self):
        evidence = {
            "prometheus": {"values": {"error_rate": 0.08, "latency_p95_seconds": 0.6}},
            "kubernetes": {"events": []},
            "gitops": {},
            "deploy_in_window": True,
            "tempo_analysis": {"entry_service_clean": False},
        }

        hypotheses = rank_hypotheses("CheckoutErrors", "checkout", evidence, None)

        self.assertEqual(hypotheses[0]["type"], "bad_deployment")
        self.assertEqual(hypotheses[0]["confidence"], 0.85)


if __name__ == "__main__":
    unittest.main()
