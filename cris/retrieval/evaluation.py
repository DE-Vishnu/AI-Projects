"""Small, transparent retrieval evaluation against hand-labelled demo cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import Release
from .chroma_store import ChromaKnowledgeStore
from .release_search import retrieve_release_evidence


def load_evaluation_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Retrieval evaluation file must contain a JSON array")
    for index, case in enumerate(raw):
        if not isinstance(case, dict) or not isinstance(case.get("release_id"), str):
            raise ValueError(f"Invalid evaluation case at index {index}")
        for key in ("expected_incident_ids", "expected_runbook_ids"):
            if not isinstance(case.get(key), list) or any(not isinstance(x, str) for x in case[key]):
                raise ValueError(f"Evaluation field '{key}' must be a list of IDs")
    return raw


def evaluate_retrieval(
    cases: list[dict[str, Any]],
    releases: list[Release],
    store: ChromaKnowledgeStore,
    *,
    k: int = 4,
) -> list[dict[str, Any]]:
    if k < 1:
        raise ValueError("k must be at least 1")
    release_by_id = {release.release_id: release for release in releases}
    reports: list[dict[str, Any]] = []

    for case in cases:
        release_id = case["release_id"]
        release = release_by_id.get(release_id)
        if release is None:
            raise ValueError(f"Evaluation references unknown release: {release_id}")

        evidence = retrieve_release_evidence(
            release, store, incident_k=k, runbook_k=k
        )
        actual_incidents = {
            str(item.metadata.get("source_id")) for item in evidence["incidents"]
        }
        actual_runbooks = {
            str(item.metadata.get("source_id")) for item in evidence["runbooks"]
        }
        expected_incidents = set(case["expected_incident_ids"])
        expected_runbooks = set(case["expected_runbook_ids"])

        # A positive case is scored by recall@k. An intentionally empty/negative
        # case is reported for human review; nearest-neighbour search always returns
        # neighbours and a low score is not yet a calibrated relevance threshold.
        incident_recall = (
            len(expected_incidents & actual_incidents) / len(expected_incidents)
            if expected_incidents else None
        )
        runbook_recall = (
            len(expected_runbooks & actual_runbooks) / len(expected_runbooks)
            if expected_runbooks else None
        )
        reports.append(
            {
                "release_id": release_id,
                "purpose": case.get("purpose", ""),
                "incident_recall_at_k": incident_recall,
                "runbook_recall_at_k": runbook_recall,
                "retrieved_incident_ids": sorted(actual_incidents),
                "retrieved_runbook_ids": sorted(actual_runbooks),
                "manual_review_required": not expected_incidents and not expected_runbooks,
            }
        )
    return reports
