import unittest
from pathlib import Path

from cris.ingestion.incidents import load_incidents_from_source
from cris.ingestion.runbooks import chunk_all_runbooks, load_markdown_runbooks
from cris.ingestion.monitoring import JsonMonitoringSource
from cris.data_loader import load_releases
from cris.retrieval.release_search import build_release_query, retrieve_release_evidence
from cris.retrieval.evaluation import evaluate_retrieval, load_evaluation_cases

ROOT = Path(__file__).resolve().parents[1]


class Day2IngestionTests(unittest.TestCase):
    def test_incidents_load_from_json_and_csv_with_same_ids(self):
        json_records = load_incidents_from_source(ROOT / "data" / "incidents.json")
        csv_records = load_incidents_from_source(ROOT / "data" / "incidents.csv")
        self.assertEqual(len(json_records), 15)
        self.assertEqual(
            [item.incident_id for item in json_records],
            [item.incident_id for item in csv_records],
        )
        self.assertEqual(json_records[0].root_cause, csv_records[0].root_cause)
        self.assertEqual(json_records[0].prevention, csv_records[0].prevention)

    def test_markdown_runbooks_parse_and_chunk_with_source_metadata(self):
        runbooks = load_markdown_runbooks(ROOT / "data" / "runbooks")
        chunks = chunk_all_runbooks(runbooks, max_chars=1_000, overlap_chars=120)
        self.assertEqual(len(runbooks), 5)
        self.assertGreaterEqual(len(chunks), 5)
        self.assertTrue(all(chunk.metadata["doc_type"] == "runbook" for chunk in chunks))
        self.assertTrue(all(chunk.metadata["runbook_id"] for chunk in chunks))
        self.assertTrue(any("Rollback steps" in chunk.text for chunk in chunks))

    def test_monitoring_source_returns_latest_snapshot(self):
        source = JsonMonitoringSource(
            ROOT / "data" / "monitoring" / "health_snapshots.json"
        )
        snapshot = source.latest_snapshot("orders_ingestion")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.metrics["cpu_utilization_pct"], 92.0)
        self.assertEqual(snapshot.captured_at.hour, 10)

    def test_monitoring_source_handles_unknown_service(self):
        source = JsonMonitoringSource(
            ROOT / "data" / "monitoring" / "health_snapshots.json"
        )
        self.assertIsNone(source.latest_snapshot("unknown_service"))

    def test_release_retrieval_query_contains_change_context(self):
        release = load_releases(ROOT / "data" / "releases.json")[0]
        query = build_release_query(release)
        self.assertIn("watermark_change", query)
        self.assertIn("orders_silver_merge", query)
        self.assertIn("late arriving records", query)

    def test_retrieval_evaluation_calculates_recall_and_flags_negative_control(self):
        class FakeResult:
            def __init__(self, source_id):
                self.metadata = {"source_id": source_id}

        class FakeStore:
            def query(self, query_text, *, doc_type, n_results, service_filter=None):
                if doc_type == "incident":
                    return [FakeResult("INC-1042")]
                return [FakeResult("RB-ORD-01")]

        releases = load_releases(ROOT / "data" / "releases.json")
        cases = load_evaluation_cases(ROOT / "data" / "retrieval_eval.json")
        reports = evaluate_retrieval(cases[:1], releases, FakeStore(), k=4)
        self.assertEqual(reports[0]["incident_recall_at_k"], 1.0)
        self.assertEqual(reports[0]["runbook_recall_at_k"], 1.0)
        negative = evaluate_retrieval(cases[2:], releases, FakeStore(), k=4)
        self.assertTrue(negative[0]["manual_review_required"])

    def test_documentation_only_release_skips_incident_and_runbook_search(self):
        class FakeStore:
            def query(self, *args, **kwargs):
                raise AssertionError("Documentation-only release should not query production history")

        releases = load_releases(ROOT / "data" / "releases.json")
        documentation_release = next(r for r in releases if r.release_id == "REL-2026-042")
        result = retrieve_release_evidence(documentation_release, FakeStore())
        self.assertEqual(result, {"incidents": [], "runbooks": []})

    def test_retrieval_calls_incidents_and_runbooks_separately(self):
        class FakeResult:
            def __init__(self, source_id, service):
                self.metadata = {"source_id": source_id, "service": service}
                self.document = f"Evidence for {source_id}"

        class FakeStore:
            def __init__(self):
                self.calls = []

            def query(self, query_text, *, doc_type, n_results, service_filter=None):
                self.calls.append((doc_type, n_results, query_text, service_filter))
                if doc_type == "incident":
                    return [FakeResult("INC-1042", service_filter or "orders_ingestion")]
                return [FakeResult("RB-ORD-01", service_filter or "orders_ingestion")]

        release = load_releases(ROOT / "data" / "releases.json")[0]
        fake_store = FakeStore()
        result = retrieve_release_evidence(release, fake_store, incident_k=3, runbook_k=2)
        self.assertEqual(result["incidents"][0].metadata["source_id"], "INC-1042")
        self.assertEqual(result["runbooks"][0].metadata["source_id"], "RB-ORD-01")
        self.assertEqual([call[0] for call in fake_store.calls], ["incident", "incident", "runbook", "runbook"])
        self.assertEqual([call[1] for call in fake_store.calls], [3, 6, 2, 4])
        self.assertEqual(fake_store.calls[0][3], "orders_ingestion")
        self.assertIsNone(fake_store.calls[1][3])
        self.assertEqual(fake_store.calls[2][3], "orders_ingestion")
        self.assertIsNone(fake_store.calls[3][3])


if __name__ == "__main__":
    unittest.main()

