"""End-to-end CRIS assessment workflow orchestrated with LangGraph."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import os
from typing import Any, TypedDict

from ..data_loader import load_releases
from ..ingestion.incidents import load_incidents_from_source
from ..ingestion.monitoring import HealthSnapshot, JsonMonitoringSource
from ..llm import LLMConfig, build_demo_analysis, generate_llm_analysis
from ..models import Incident, Release
from ..retrieval.chroma_store import ChromaKnowledgeStore, RetrievedDocument
from ..retrieval.release_search import retrieve_release_evidence
from ..scoring import RiskAssessment, assess_release


class AssessmentState(TypedDict, total=False):
    release_id: str
    project_root: str
    chroma_dir: str
    llm_enabled: bool
    llm_config: LLMConfig
    release: Release
    incidents: list[Incident]
    health_snapshot: HealthSnapshot | None
    health_payload: dict[str, Any] | None
    evidence: dict[str, list[RetrievedDocument]]
    risk_assessment: RiskAssessment
    ai_analysis: dict[str, Any]
    analysis_mode: str
    workflow_steps: list[str]


def _load_release_node(state: AssessmentState) -> dict[str, Any]:
    root = Path(state["project_root"])
    releases = load_releases(root / "data" / "releases.json")
    release = next(
        (item for item in releases if item.release_id.casefold() == state["release_id"].casefold()),
        None,
    )
    if release is None:
        raise ValueError(f"Unknown release ID: {state['release_id']}")
    incidents = load_incidents_from_source(root / "data" / "incidents.json")
    return {
        "release": release,
        "incidents": incidents,
        "workflow_steps": ["Loaded the selected release and normalized historical incident records."],
    }


def _retrieve_evidence_node(state: AssessmentState) -> dict[str, Any]:
    store = ChromaKnowledgeStore(Path(state["chroma_dir"]))
    if store.count == 0:
        raise RuntimeError(
            "The CRIS ChromaDB collection is empty. Run 'python -m cris.day2 index --reset' first."
        )
    evidence = retrieve_release_evidence(
        state["release"], store, incident_k=5, runbook_k=5
    )
    return {
        "evidence": evidence,
        "workflow_steps": state.get("workflow_steps", []) + [
            f"Retrieved {len(evidence['incidents'])} incident records and {len(evidence['runbooks'])} runbook sections from ChromaDB."
        ],
    }


def _load_monitoring_node(state: AssessmentState) -> dict[str, Any]:
    root = Path(state["project_root"])
    source = JsonMonitoringSource(root / "data" / "monitoring" / "health_snapshots.json")
    snapshot = source.latest_snapshot(state["release"].service)
    payload = None
    scoring_snapshot = snapshot
    if snapshot:
        now = datetime.now(snapshot.captured_at.tzinfo)
        age_minutes = max(0.0, (now - snapshot.captured_at).total_seconds() / 60.0)
        max_age_minutes = float(os.getenv("CRIS_MONITORING_MAX_AGE_MINUTES", "1440"))
        status = "stale" if age_minutes > max_age_minutes else "available"
        payload = {
            "service": snapshot.service,
            "captured_at": snapshot.captured_at.isoformat(),
            "source": snapshot.source,
            "metrics": snapshot.metrics,
            "age_minutes": round(age_minutes, 1),
            "max_age_minutes": max_age_minutes,
            "status": status,
        }
        if status == "stale":
            scoring_snapshot = None
    return {
        "health_snapshot": scoring_snapshot,
        "health_payload": payload,
        "workflow_steps": state.get("workflow_steps", []) + [
            "Loaded a fresh timestamped monitoring snapshot for the release service."
            if snapshot and scoring_snapshot else (
                "The monitoring snapshot is stale and was excluded from scoring."
                if snapshot else "No monitoring snapshot was found for this release service."
            )
        ],
    }


def merge_health_into_release(
    release: Release,
    snapshot: HealthSnapshot | None,
) -> Release:
    """Copy supported monitoring metrics into a release for deterministic scoring."""
    if snapshot is None:
        # Never treat metrics embedded in a sample release record as live telemetry.
        # With no monitoring snapshot, all operational signals remain unknown.
        return replace(release, operational_signals={})
    supported = {
        "error_rate_pct",
        "latency_p95_ms",
        "pipeline_lag_minutes",
        "cpu_utilization_pct",
        "memory_utilization_pct",
        "job_failure_rate_pct",
        "data_freshness_lag_minutes",
    }
    metrics = {name: snapshot.metrics.get(name) for name in supported}
    return replace(release, operational_signals=metrics)


def _score_node(state: AssessmentState) -> dict[str, Any]:
    enriched_release = merge_health_into_release(
        state["release"], state.get("health_snapshot")
    )
    # Keep the full incident source for ID-to-record lookup, but score only the
    # candidates ChromaDB actually retrieved for this release.
    retrieved_incidents = state["evidence"].get("incidents", [])
    semantic_similarities = {
        str((item.metadata or {}).get("source_id")): item.cosine_similarity
        for item in retrieved_incidents
        if (item.metadata or {}).get("source_id")
    }
    retrieved_ids = set(semantic_similarities)
    candidate_incidents = [
        incident for incident in state["incidents"]
        if incident.incident_id in retrieved_ids
    ]
    assessment = assess_release(
        enriched_release,
        candidate_incidents,
        semantic_similarities=semantic_similarities,
    )
    return {
        "release": enriched_release,
        "risk_assessment": assessment,
        "workflow_steps": state.get("workflow_steps", []) + [
            f"Calculated historical risk using {len(candidate_incidents)} ChromaDB-retrieved incidents only; blended semantic relevance with structured overlap and incident severity.",
            "Mapped monitoring metrics into the risk model and calculated all five risk dimensions.",
        ],
    }


def _analysis_node(state: AssessmentState) -> dict[str, Any]:
    release = state["release"]
    assessment = state["risk_assessment"]
    evidence = state["evidence"]
    config: LLMConfig = state.get("llm_config", LLMConfig.from_environment())
    if state.get("llm_enabled", True) and config.is_configured:
        analysis = generate_llm_analysis(
            config,
            release,
            assessment,
            evidence["incidents"],
            evidence["runbooks"],
            state.get("health_payload"),
        )
        mode = f"LLM: {config.model}"
        step = "Generated an evidence-grounded assessment using the configured LLM provider."
    else:
        analysis = build_demo_analysis(
            release,
            assessment,
            evidence["incidents"],
            evidence["runbooks"],
            state.get("health_payload"),
        )
        mode = "DEMO MODE — no LLM provider called"
        step = "Generated a deterministic demo summary because no LLM credentials/model were configured or LLM use was disabled."
    return {
        "ai_analysis": analysis,
        "analysis_mode": mode,
        "workflow_steps": state.get("workflow_steps", []) + [step],
    }


def build_assessment_graph():
    """Build and compile the release-assessment graph."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph is not installed. Install requirements.txt before running CRIS."
        ) from exc

    graph = StateGraph(AssessmentState)
    graph.add_node("load_release", _load_release_node)
    graph.add_node("retrieve_evidence", _retrieve_evidence_node)
    graph.add_node("load_monitoring", _load_monitoring_node)
    graph.add_node("score_release", _score_node)
    graph.add_node("generate_analysis", _analysis_node)
    graph.add_edge(START, "load_release")
    graph.add_edge("load_release", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "load_monitoring")
    graph.add_edge("load_monitoring", "score_release")
    graph.add_edge("score_release", "generate_analysis")
    graph.add_edge("generate_analysis", END)
    return graph.compile()


def run_assessment(
    release_id: str,
    project_root: Path,
    *,
    chroma_dir: Path | None = None,
    llm_enabled: bool = True,
    llm_config: LLMConfig | None = None,
) -> AssessmentState:
    """Run the complete CRIS workflow and return its final state."""
    graph = build_assessment_graph()
    state: AssessmentState = {
        "release_id": release_id,
        "project_root": str(project_root.resolve()),
        "chroma_dir": str((chroma_dir or project_root / "storage" / "chroma").resolve()),
        "llm_enabled": llm_enabled,
        "llm_config": llm_config or LLMConfig.from_environment(),
    }
    return graph.invoke(state)
