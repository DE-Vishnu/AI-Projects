import unittest
from pathlib import Path

from cris.data_loader import load_incidents, load_releases
from cris.models import DataValidationError, Release
from cris.scoring import assess_release

ROOT = Path(__file__).resolve().parents[1]


class RiskScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.incidents = load_incidents(ROOT / "data" / "incidents.json")
        cls.releases = {r.release_id: r for r in load_releases(ROOT / "data" / "releases.json")}

    def test_high_risk_release_matches_historical_incident(self):
        report = assess_release(self.releases["REL-2026-041"], self.incidents)
        self.assertGreaterEqual(report.total_score, 80)
        self.assertEqual(report.risk_band, "Critical")
        self.assertEqual(report.matched_incidents[0].incident_id, "INC-1042")
        self.assertEqual(report.evidence_coverage_pct, 100)

    def test_low_risk_release_scores_lower_than_high_risk(self):
        high = assess_release(self.releases["REL-2026-041"], self.incidents)
        low = assess_release(self.releases["REL-2026-042"], self.incidents)
        self.assertLess(low.total_score, high.total_score)
        self.assertEqual(low.risk_band, "Low")
        self.assertEqual(low.evidence_coverage_pct, 100)

    def test_payment_release_surfaces_related_incident(self):
        report = assess_release(self.releases["REL-2026-043"], self.incidents)
        self.assertTrue(report.matched_incidents)
        self.assertEqual(report.matched_incidents[0].incident_id, "INC-0972")
        self.assertTrue(any("credential" in r.lower() or "token" in r.lower() for r in report.recommendations))

    def test_missing_operational_signals_are_not_treated_as_healthy(self):
        release_dict = {
            "release_id": "REL-UNKNOWN",
            "name": "Release with no telemetry",
            "service": "unknown_service",
            "description": "Small application change",
            "change_types": ["documentation_only"],
            "changed_components": ["readme"],
            "downstream_dependencies": [],
            "criticality": "low",
            "test_status": "passed",
            "rollback_tested": True,
            "canary_enabled": True,
            "approvals_complete": True,
            "operational_signals": {},
        }
        report = assess_release(Release.from_dict(release_dict), self.incidents)
        ops = next(d for d in report.dimensions if d.key == "operational_health")
        self.assertEqual(report.evidence_coverage_pct, 0)
        self.assertEqual(ops.score, 7.5)
        self.assertTrue(any("reduce confidence" in c for c in report.caveats))

    def test_invalid_boolean_is_rejected(self):
        release_dict = {
            "release_id": "BAD",
            "name": "Bad release",
            "service": "svc",
            "description": "desc",
            "change_types": ["documentation_only"],
            "changed_components": [],
            "downstream_dependencies": [],
            "criticality": "low",
            "test_status": "passed",
            "rollback_tested": "yes",
            "canary_enabled": True,
            "approvals_complete": True,
            "operational_signals": {},
        }
        with self.assertRaises(DataValidationError):
            Release.from_dict(release_dict)


if __name__ == "__main__":
    unittest.main()
