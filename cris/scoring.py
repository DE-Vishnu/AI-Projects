"""Explainable, deterministic release-risk scoring for CRIS.

The score is a prioritization index, NOT a probability of an incident.
Weights and thresholds are prototype assumptions that should be calibrated
against real deployment outcomes before production use.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

from .models import Incident, Release

WEIGHTS = {
    "historical_similarity": 30,
    "change_sensitivity": 20,
    "blast_radius": 20,
    "operational_health": 15,
    "release_readiness": 15,
}

CHANGE_SENSITIVITY = {
    "watermark_change": (7, "Watermark changes can skip or reprocess records."),
    "merge_logic": (7, "MERGE-condition changes can introduce duplicates or missed updates."),
    "schema_change": (6, "Schema changes can break downstream consumers."),
    "api_contract_change": (6, "API contract changes can break integrations or consumers."),
    "authentication_change": (8, "Authentication changes can affect access across dependent systems."),
    "infrastructure_change": (6, "Infrastructure changes can affect availability and capacity."),
    "configuration_change": (5, "Configuration changes can alter runtime behaviour."),
    "dependency_upgrade": (4, "Dependency upgrades can introduce compatibility changes."),
    "transformation_logic": (4, "Transformation changes can alter data correctness."),
    "orchestration_change": (5, "Orchestration changes can affect scheduling and dependencies."),
    "documentation_only": (0, "Documentation-only changes have limited direct runtime impact."),
}

# Maximum raw risk points per operational signal. Missing signals are assigned
# half of their maximum risk contribution, rather than being treated as healthy.
SIGNAL_MAX = {
    "error_rate_pct": 5.0,
    "latency_p95_ms": 4.0,
    "pipeline_lag_minutes": 4.0,
    "cpu_utilization_pct": 4.0,
    "memory_utilization_pct": 4.0,
    "job_failure_rate_pct": 4.0,
    "data_freshness_lag_minutes": 4.0,
}


@dataclass
class DimensionResult:
    key: str
    label: str
    score: float
    max_score: float
    explanation: str
    evidence: list[str]


@dataclass
class IncidentMatch:
    incident_id: str
    title: str
    service: str
    similarity_pct: float
    severity: str
    root_cause: str
    impact: str
    prevention: list[str]
    semantic_similarity: float | None = None
    historical_signal_pct: float | None = None
    severity_weight: float = 1.0


@dataclass
class RiskAssessment:
    release_id: str
    release_name: str
    total_score: int
    risk_band: str
    dimensions: list[DimensionResult]
    matched_incidents: list[IncidentMatch]
    evidence_coverage_pct: int
    available_operational_signals: int
    total_operational_signals: int
    recommendations: list[str]
    caveats: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", value.lower()) if len(token) > 1}


def _overlap_ratio(left: Iterable[str], right: Iterable[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set:
        return 0.0
    return len(left_set & right_set) / len(left_set)


def _incident_similarity(release: Release, incident: Incident) -> float:
    """Return 0-100 similarity from service, component, change and keyword overlap."""
    service_score = 35.0 if release.service.casefold() == incident.service.casefold() else 0.0
    component_score = 30.0 * _overlap_ratio(
        [x.casefold() for x in release.changed_components],
        [x.casefold() for x in incident.affected_components],
    )
    change_score = 25.0 * _overlap_ratio(
        [x.casefold() for x in release.change_types],
        [x.casefold() for x in incident.change_types],
    )
    release_context = _tokens(" ".join([release.description, *release.changed_components, *release.change_types]))
    keyword_score = 10.0 * _overlap_ratio(
        [x.casefold() for x in incident.trigger_keywords],
        release_context,
    )
    return round(min(100.0, service_score + component_score + change_score + keyword_score), 1)


def _risk_band(score: int) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 35:
        return "Moderate"
    return "Low"


def _operational_signal_risk(name: str, value: float) -> float:
    if name == "error_rate_pct":
        if value <= 0.5: return 0.0
        if value <= 1: return 1.0
        if value <= 2: return 2.5
        if value <= 5: return 4.0
        return 5.0
    if name == "latency_p95_ms":
        if value <= 500: return 0.0
        if value <= 1000: return 1.0
        if value <= 2000: return 2.0
        if value <= 5000: return 3.0
        return 4.0
    if name == "pipeline_lag_minutes":
        if value <= 5: return 0.0
        if value <= 15: return 1.0
        if value <= 30: return 2.0
        if value <= 60: return 3.0
        return 4.0
    if name == "cpu_utilization_pct":
        if value <= 60: return 0.0
        if value <= 75: return 0.5
        if value <= 85: return 1.5
        if value <= 95: return 3.0
        return 4.0
    if name == "memory_utilization_pct":
        if value <= 60: return 0.0
        if value <= 75: return 1.0
        if value <= 85: return 2.0
        if value <= 95: return 3.0
        return 4.0
    if name == "job_failure_rate_pct":
        if value <= 0.5: return 0.0
        if value <= 1.0: return 1.0
        if value <= 2.0: return 2.0
        if value <= 5.0: return 3.0
        return 4.0
    if name == "data_freshness_lag_minutes":
        if value <= 5: return 0.0
        if value <= 15: return 1.0
        if value <= 30: return 2.0
        if value <= 60: return 3.0
        return 4.0
    raise KeyError(name)


def _operational_health(release: Release) -> tuple[float, list[str], int]:
    evidence: list[str] = []
    raw_risk = 0.0
    available = 0
    for name, maximum in SIGNAL_MAX.items():
        value = release.operational_signals.get(name)
        if value is None:
            # Conservative neutral assumption for unknown data; never silently
            # interpret missing telemetry as a healthy signal.
            raw_risk += maximum * 0.5
            evidence.append(f"{name}: not supplied; treated as unknown (neutral risk assumption)")
            continue
        available += 1
        risk = _operational_signal_risk(name, value)
        raw_risk += risk
        evidence.append(f"{name}: {value:g}; contributes {risk:g}/{maximum:g} risk points")
    score = min(15.0, (raw_risk / sum(SIGNAL_MAX.values())) * 15.0)
    return round(score, 1), evidence, available


def _change_sensitivity(release: Release) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []
    for change_type in release.change_types:
        points, explanation = CHANGE_SENSITIVITY.get(
            change_type,
            (3, f"Unclassified change type '{change_type}' receives a conservative default weight."),
        )
        score += points
        evidence.append(f"{change_type}: +{points} — {explanation}")
    return round(min(20.0, score), 1), evidence


def _blast_radius(release: Release) -> tuple[float, list[str]]:
    criticality_points = {"critical": 10, "high": 8, "medium": 5, "low": 2}.get(release.criticality, 6)
    dependency_points = min(6, len(release.downstream_dependencies) * 2)
    component_points = min(4, max(0, len(release.changed_components) - 1))
    total = min(20.0, criticality_points + dependency_points + component_points)
    evidence = [
        f"Service criticality '{release.criticality}': +{criticality_points}",
        f"{len(release.downstream_dependencies)} downstream dependencies: +{dependency_points}",
        f"{len(release.changed_components)} changed components: +{component_points}",
    ]
    if release.downstream_dependencies:
        evidence.append("Downstream: " + ", ".join(release.downstream_dependencies))
    return round(total, 1), evidence


def _release_readiness(release: Release) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []
    test_points = {"passed": 0, "partial": 4, "failed": 8, "not_run": 10}.get(release.test_status, 6)
    score += test_points
    evidence.append(f"Test status '{release.test_status}': +{test_points}")
    if not release.rollback_tested:
        score += 3
        evidence.append("Rollback has not been tested: +3")
    else:
        evidence.append("Rollback tested: +0")
    if not release.canary_enabled:
        score += 1
        evidence.append("Canary deployment disabled: +1")
    else:
        evidence.append("Canary deployment enabled: +0")
    if not release.approvals_complete:
        score += 1
        evidence.append("Required approvals incomplete: +1")
    else:
        evidence.append("Required approvals complete: +0")
    return round(min(15.0, score), 1), evidence


def _recommendations(release: Release, matches: list[IncidentMatch]) -> list[str]:
    suggestions: list[str] = []
    changes = set(release.change_types)
    if "watermark_change" in changes:
        suggestions.append("Test watermark boundaries, late-arriving records, replay behaviour and backfill safety.")
    if "merge_logic" in changes:
        suggestions.append("Validate MERGE keys, source uniqueness, idempotency and duplicate/missing-row scenarios.")
    if "schema_change" in changes or "api_contract_change" in changes:
        suggestions.append("Run backward-compatibility checks against downstream consumers before deployment.")
    if "authentication_change" in changes:
        suggestions.append("Validate service identities, least-privilege access and token/credential rotation paths.")
    if "infrastructure_change" in changes or "configuration_change" in changes:
        suggestions.append("Compare effective configuration with the previous release and validate capacity limits.")
    if not release.rollback_tested:
        suggestions.append("Test and document the rollback procedure before approving the release.")
    if not release.canary_enabled:
        suggestions.append("Use a canary or staged rollout and define an explicit observation window.")
    if release.test_status != "passed":
        suggestions.append("Complete the relevant automated regression and data-quality tests before deployment.")
    if matches:
        top = matches[0]
        suggestions.append(f"Review {top.incident_id} ({top.title}) and verify its documented prevention steps.")
    if not release.operational_signals or all(v is None for v in release.operational_signals.values()):
        suggestions.append("Capture baseline error rate, p95 latency, pipeline lag and CPU before making the release decision.")
    if not suggestions:
        suggestions.append("Proceed through the normal approval process and monitor the release against its baseline SLOs.")
    # Keep the report practical and avoid duplicate recommendations.
    return list(dict.fromkeys(suggestions))


def _severity_weight(severity: str) -> float:
    """Convert historical incident severity to a conservative impact multiplier."""
    normalized = severity.casefold().replace("-", "").replace("_", "")
    return {
        "sev1": 1.00, "critical": 1.00,
        "sev2": 0.90, "high": 0.90,
        "sev3": 0.80, "medium": 0.80,
        "sev4": 0.70, "low": 0.70,
    }.get(normalized, 0.85)


def assess_release(
    release: Release,
    incidents: list[Incident],
    *,
    semantic_similarities: dict[str, float] | None = None,
) -> RiskAssessment:
    """Assess a release using supplied incident candidates.

    When semantic_similarities is supplied, `incidents` must be the ChromaDB
    retrieved subset. The historical signal blends Chroma semantic relevance
    (60%) with structured field overlap (40%), then adjusts for past incident
    severity. This is an illustrative prioritization heuristic, not a failure
    probability. Without semantic scores, the legacy CLI uses structured
    matching against the incident list it is given.
    """
    retrieved_mode = semantic_similarities is not None
    scored_incidents: list[tuple[float, float, float | None, float, Incident]] = []
    for incident in incidents:
        structured_similarity = _incident_similarity(release, incident)
        if retrieved_mode:
            raw_semantic = float(semantic_similarities.get(incident.incident_id, 0.0))
            semantic_similarity = max(0.0, min(1.0, raw_semantic))
            severity_weight = _severity_weight(incident.severity)
            blended_similarity = (0.60 * semantic_similarity * 100.0) + (0.40 * structured_similarity)
            historical_signal = blended_similarity * severity_weight
        else:
            semantic_similarity = None
            severity_weight = 1.0
            historical_signal = structured_similarity
        scored_incidents.append((historical_signal, structured_similarity, semantic_similarity, severity_weight, incident))

    scored_incidents.sort(key=lambda item: item[0], reverse=True)
    matches = [
        IncidentMatch(
            incident_id=incident.incident_id,
            title=incident.title,
            service=incident.service,
            similarity_pct=structured_similarity,
            severity=incident.severity,
            root_cause=incident.root_cause,
            impact=incident.impact,
            prevention=incident.prevention,
            semantic_similarity=semantic_similarity,
            historical_signal_pct=historical_signal,
            severity_weight=severity_weight,
        )
        for historical_signal, structured_similarity, semantic_similarity, severity_weight, incident in scored_incidents[:3]
        if historical_signal >= 20
    ]
    best_signal = matches[0].historical_signal_pct if matches else 0.0
    history_score = round((float(best_signal or 0.0) / 100.0) * WEIGHTS["historical_similarity"], 1)
    if matches and retrieved_mode:
        history_evidence = [
            (
                f"{m.incident_id}: Chroma cosine similarity {m.semantic_similarity:.3f}, "
                f"structured overlap {m.similarity_pct:g}%, severity {m.severity} "
                f"(weight {m.severity_weight:.2f}) → historical signal {m.historical_signal_pct:.1f}%"
            )
            for m in matches
        ]
    elif matches:
        history_evidence = [
            f"Closest match: {m.incident_id} ({m.title}) at {m.similarity_pct:g}% structured similarity"
            for m in matches
        ]
    else:
        history_evidence = ["No sufficiently similar incident found in the supplied incident candidates."]

    change_score, change_evidence = _change_sensitivity(release)
    blast_score, blast_evidence = _blast_radius(release)
    ops_score, ops_evidence, available_signals = _operational_health(release)
    readiness_score, readiness_evidence = _release_readiness(release)

    dimensions = [
        DimensionResult("historical_similarity", "Historical incident similarity", history_score, 30,
                        "Higher scores mean this release resembles changes associated with previous incidents.", history_evidence),
        DimensionResult("change_sensitivity", "Change sensitivity", change_score, 20,
                        "Higher scores mean the release touches more failure-sensitive change types.", change_evidence),
        DimensionResult("blast_radius", "Impact and blast radius", blast_score, 20,
                        "Higher scores mean a more critical service or a wider downstream impact.", blast_evidence),
        DimensionResult("operational_health", "Operational signals", ops_score, 15,
                        "Higher scores mean supplied telemetry is unhealthy; missing telemetry receives a neutral risk assumption.", ops_evidence),
        DimensionResult("release_readiness", "Release readiness", readiness_score, 15,
                        "Higher scores mean tests, rollback, canary or approval readiness is incomplete.", readiness_evidence),
    ]
    total = int(round(sum(d.score for d in dimensions)))
    total = max(0, min(100, total))
    evidence_pct = int(round((available_signals / len(SIGNAL_MAX)) * 100))
    caveats = [
        "Risk index is a prioritization score, not a probability that an incident will occur.",
        "Weights and thresholds are illustrative and must be calibrated against real release outcomes.",
    ]
    if evidence_pct < 100:
        caveats.append(f"Operational telemetry coverage is {evidence_pct}%; missing signals reduce confidence in this assessment.")
    if not incidents:
        caveats.append("ChromaDB supplied no incident candidates; the historical-risk dimension is zero and should be treated as unknown, not proof of safety.")
    if retrieved_mode:
        caveats.append("Historical-risk heuristic uses retrieved incidents only: 60% Chroma semantic relevance, 40% structured field overlap, adjusted by historical incident severity. These weights are illustrative.")

    return RiskAssessment(
        release_id=release.release_id,
        release_name=release.name,
        total_score=total,
        risk_band=_risk_band(total),
        dimensions=dimensions,
        matched_incidents=matches,
        evidence_coverage_pct=evidence_pct,
        available_operational_signals=available_signals,
        total_operational_signals=len(SIGNAL_MAX),
        recommendations=_recommendations(release, matches),
        caveats=caveats,
    )
