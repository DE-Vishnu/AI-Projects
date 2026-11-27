import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
import io
import json

from cris.data_loader import load_releases
from cris.ingestion.monitoring import HealthSnapshot
from cris.llm import (
    _validate_and_clean_analysis,
    build_analysis_messages,
    build_demo_analysis,
    generate_llm_analysis,
    LLMConfig,
)
from cris.retrieval.chroma_store import RetrievedDocument
from cris.scoring import assess_release
from cris.workflow.assessment import _score_node, merge_health_into_release
from cris.ingestion.incidents import load_incidents_from_source

ROOT = Path(__file__).resolve().parents[1]


class Day3WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = load_releases(ROOT / "data" / "releases.json")[0]
        cls.incidents = load_incidents_from_source(ROOT / "data" / "incidents.json")
        cls.snapshot = HealthSnapshot.from_dict({
            "service": "orders_ingestion",
            "captured_at": "2026-11-26T10:30:00+05:30",
            "source": "mock_new_relic_adapter",
            "metrics": {
                "error_rate_pct": 2.4,
                "latency_p95_ms": 2800,
                "cpu_utilization_pct": 92,
                "memory_utilization_pct": 86,
                "pipeline_lag_minutes": 45,
                "job_failure_rate_pct": 3.1,
                "data_freshness_lag_minutes": 48,
            },
        })

    def test_health_snapshot_overrides_release_signals_and_maps_all_seven(self):
        release_without_extra_metrics = replace(
            self.release,
            operational_signals={
                key: value for key, value in self.release.operational_signals.items()
                if key in {"error_rate_pct", "latency_p95_ms", "pipeline_lag_minutes", "cpu_utilization_pct"}
            },
        )
        enriched = merge_health_into_release(release_without_extra_metrics, self.snapshot)
        self.assertEqual(len(enriched.operational_signals), 7)
        self.assertEqual(enriched.operational_signals["memory_utilization_pct"], 86.0)
        self.assertEqual(enriched.operational_signals["job_failure_rate_pct"], 3.1)
        # dataclasses.replace returns a new Release; the source record stays unchanged.
        self.assertNotIn("memory_utilization_pct", release_without_extra_metrics.operational_signals)

    def test_no_monitoring_snapshot_does_not_reuse_release_embedded_sample_metrics(self):
        without_live_health = merge_health_into_release(self.release, None)
        self.assertEqual(without_live_health.operational_signals, {})

    def test_risk_assessment_uses_all_seven_health_signals(self):
        enriched = merge_health_into_release(self.release, self.snapshot)
        report = assess_release(enriched, self.incidents)
        ops = next(d for d in report.dimensions if d.key == "operational_health")
        self.assertEqual(report.available_operational_signals, 7)
        self.assertEqual(report.total_operational_signals, 7)
        self.assertEqual(report.evidence_coverage_pct, 100)
        self.assertGreater(ops.score, 0)

    def test_analysis_prompt_contains_release_and_retrieved_sources(self):
        incident = RetrievedDocument(
            document="INC-1042: watermark change caused missing records.",
            metadata={"source_id": "INC-1042", "title": "Watermark incident", "service": "orders_ingestion"},
            distance=0.2,
            cosine_similarity=0.8,
        )
        runbook = RetrievedDocument(
            document="RB-ORD-01: validate watermark boundaries before deployment.",
            metadata={"source_id": "RB-ORD-01", "section": "Pre-deployment checks", "service": "orders_ingestion"},
            distance=0.25,
            cosine_similarity=0.75,
        )
        enriched = merge_health_into_release(self.release, self.snapshot)
        report = assess_release(enriched, self.incidents)
        messages, allowed = build_analysis_messages(
            enriched, report, [incident], [runbook],
            {"service": "orders_ingestion", "source": "mock_new_relic_adapter"},
        )
        prompt = messages[1]["content"]
        self.assertIn("REL-2026-041", prompt)
        self.assertIn("INC-1042", prompt)
        self.assertIn("RB-ORD-01", prompt)
        self.assertEqual(allowed, {"INC-1042", "RB-ORD-01"})

    def test_model_citations_are_restricted_to_retrieved_source_ids(self):
        cleaned = _validate_and_clean_analysis({
            "executive_summary": "Review this release.",
            "release_recommendation": "HOLD_FOR_REVIEW",
            "key_risks": [{"risk": "Watermark failure", "why_it_matters": "Records may be skipped", "evidence_ids": ["INC-1042", "INC-FAKE"]}],
            "recommended_checks": [{"action": "Validate replay", "reason": "Runbook says so", "evidence_ids": ["RB-ORD-01"]}],
            "rollback_triggers": [{"trigger": "Lag exceeds SLO", "source_id": "RB-FAKE"}],
            "unknowns": [],
        }, {"INC-1042", "RB-ORD-01"})
        self.assertEqual(cleaned["key_risks"][0]["evidence_ids"], ["INC-1042"])
        self.assertEqual(cleaned["rollback_triggers"][0]["source_id"], "")

    def test_llm_adapter_parses_openai_compatible_response_and_validates_citations(self):
        incident = RetrievedDocument(
            document="INC-1042: similar watermark failure.",
            metadata={"source_id": "INC-1042", "title": "Watermark failure", "service": "orders_ingestion"},
            distance=0.2,
            cosine_similarity=0.8,
        )
        runbook = RetrievedDocument(
            document="RB-ORD-01: validate source keys.",
            metadata={"source_id": "RB-ORD-01", "section": "Checks", "service": "orders_ingestion"},
            distance=0.25,
            cosine_similarity=0.75,
        )
        enriched = merge_health_into_release(self.release, self.snapshot)
        report = assess_release(enriched, self.incidents)
        model_content = json.dumps({
            "executive_summary": "Review the watermark change.",
            "key_risks": [{"risk": "Late records may be skipped", "why_it_matters": "A prior incident had this failure", "evidence_ids": ["INC-1042", "INC-FAKE"]}],
            "recommended_checks": [{"action": "Validate keys", "reason": "Runbook procedure", "evidence_ids": ["RB-ORD-01"]}],
            "rollback_triggers": [],
            "release_recommendation": "HOLD_FOR_REVIEW",
            "unknowns": [],
        })
        fake_response = {
            "model": "test-model",
            "choices": [{"message": {"content": model_content}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 180, "total_tokens": 1380},
        }

        class FakeHTTPResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps(fake_response).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse()) as mocked_urlopen:
            result = generate_llm_analysis(
                LLMConfig("https://example.test/v1", "test-key", "gpt-6-luna"),
                enriched,
                report,
                [incident],
                [runbook],
                {"service": "orders_ingestion"},
            )
        request = mocked_urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request_body["response_format"], {"type": "json_object"})
        self.assertEqual(request_body["max_completion_tokens"], 8000)
        self.assertEqual(request_body["reasoning_effort"], "low")
        self.assertNotIn("temperature", request_body)
        self.assertEqual(result["release_recommendation"], "HOLD_FOR_REVIEW")
        self.assertEqual(result["key_risks"][0]["evidence_ids"], ["INC-1042"])
        self.assertEqual(result["token_usage"]["total_tokens"], 1380)

    def test_llm_empty_response_reports_token_limit_diagnostics(self):
        fake_response = {
            "choices": [{"message": {"content": None}, "finish_reason": "length"}],
            "usage": {
                "completion_tokens": 8000,
                "completion_tokens_details": {"reasoning_tokens": 7900},
            },
        }

        class FakeHTTPResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(fake_response).encode("utf-8")

        enriched = merge_health_into_release(self.release, self.snapshot)
        report = assess_release(enriched, self.incidents)
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse()):
            with self.assertRaisesRegex(
                Exception, "completion-token budget.*reasoning_tokens=7900"
            ):
                generate_llm_analysis(
                    LLMConfig("https://example.test/v1", "test-key", "gpt-6-luna"),
                    enriched, report, [], [], {"service": "orders_ingestion"},
                )

    def test_workflow_scores_only_chromadb_retrieved_incidents(self):
        retrieved = RetrievedDocument(
            document="INC-1042: watermark and MERGE failure.",
            metadata={"source_id": "INC-1042", "title": "Watermark incident", "service": "orders_ingestion"},
            distance=0.2,
            cosine_similarity=0.8,
        )
        state = {
            "release": self.release,
            "incidents": self.incidents,  # full local file is available for ID lookup
            "evidence": {"incidents": [retrieved]},
            "health_snapshot": self.snapshot,
            "workflow_steps": [],
        }
        result = _score_node(state)
        report = result["risk_assessment"]
        self.assertEqual([m.incident_id for m in report.matched_incidents], ["INC-1042"])
        history = next(d for d in report.dimensions if d.key == "historical_similarity")
        self.assertTrue(any("Chroma cosine similarity 0.800" in line for line in history.evidence))
        self.assertEqual(history.score, 26.1)  # (80% * 60% + 97.5% * 40%) * SEV1 * 30
        self.assertTrue(any("retrieved incidents only" in step for step in result["workflow_steps"]))

    def test_workflow_does_not_score_unretrieved_incidents(self):
        state = {
            "release": self.release,
            "incidents": self.incidents,
            "evidence": {"incidents": []},
            "health_snapshot": self.snapshot,
            "workflow_steps": [],
        }
        result = _score_node(state)
        report = result["risk_assessment"]
        history = next(d for d in report.dimensions if d.key == "historical_similarity")
        self.assertEqual(history.score, 0.0)
        self.assertEqual(report.matched_incidents, [])
        self.assertTrue(any("ChromaDB supplied no incident candidates" in item for item in report.caveats))

    def test_llm_cannot_downgrade_required_review_for_high_risk_score(self):
        incident = RetrievedDocument(
            document="INC-1042: similar watermark failure.",
            metadata={"source_id": "INC-1042", "title": "Watermark failure", "service": "orders_ingestion"},
            distance=0.2,
            cosine_similarity=0.8,
        )
        runbook = RetrievedDocument(
            document="RB-ORD-01: validate source keys.",
            metadata={"source_id": "RB-ORD-01", "section": "Checks", "service": "orders_ingestion"},
            distance=0.25,
            cosine_similarity=0.75,
        )
        enriched = merge_health_into_release(self.release, self.snapshot)
        report = assess_release(enriched, self.incidents)
        model_content = json.dumps({
            "executive_summary": "Looks ready.",
            "key_risks": [], "recommended_checks": [], "rollback_triggers": [],
            "release_recommendation": "STANDARD_REVIEW", "unknowns": [],
        })
        fake_response = {"choices": [{"message": {"content": model_content}}]}

        class FakeHTTPResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(fake_response).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse()) as mocked_urlopen:
            result = generate_llm_analysis(
                LLMConfig("https://example.test/v1", "test-key", "test-model"),
                enriched, report, [incident], [runbook], {"service": "orders_ingestion"},
            )
        request = mocked_urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request_body["temperature"], 0.2)
        self.assertEqual(result["release_recommendation"], "HOLD_FOR_REVIEW")
        self.assertEqual(result["model_recommendation"], "STANDARD_REVIEW")
        self.assertIn("requires at least HOLD_FOR_REVIEW", result["recommendation_note"])

    def test_demo_analysis_is_explicit_about_not_calling_an_llm(self):
        enriched = merge_health_into_release(self.release, self.snapshot)
        report = assess_release(enriched, self.incidents)
        result = build_demo_analysis(enriched, report, [], [], None)
        self.assertIn("no LLM provider was called", result["executive_summary"])
        self.assertIn("DETERMINISTIC", result["citation_note"].upper())


if __name__ == "__main__":
    unittest.main()
