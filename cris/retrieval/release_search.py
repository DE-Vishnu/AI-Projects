"""Build release queries and retrieve service-aware semantic evidence."""

from __future__ import annotations

from ..models import Release
from .chroma_store import ChromaKnowledgeStore, RetrievedDocument


def build_release_query(release: Release) -> str:
    """Compose release context used for semantic search (not an LLM prompt)."""
    return "\n".join(
        [
            f"Upcoming release: {release.name}",
            f"Service: {release.service}",
            f"Release description: {release.description}",
            f"Change types: {', '.join(release.change_types)}",
            f"Changed components: {', '.join(release.changed_components)}",
            f"Downstream dependencies: {', '.join(release.downstream_dependencies)}",
        ]
    )


def _merge_service_first(
    same_service: list[RetrievedDocument],
    global_results: list[RetrievedDocument],
    *,
    limit: int,
) -> list[RetrievedDocument]:
    """Keep same-service results first, then append unique cross-service analogies."""
    merged: list[RetrievedDocument] = []
    seen: set[str] = set()
    for item in same_service + global_results:
        metadata = item.metadata or {}
        source_id = str(metadata.get("source_id", ""))
        if metadata.get("doc_type") == "runbook":
            # A runbook can have many useful chunks; dedupe chunks, not the parent document.
            key = f"{source_id}::{metadata.get('chunk_index', item.document[:100])}"
        else:
            key = source_id or item.document[:100]
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def retrieve_release_evidence(
    release: Release,
    store: ChromaKnowledgeStore,
    *,
    incident_k: int = 4,
    runbook_k: int = 4,
) -> dict[str, list[RetrievedDocument]]:
    """Retrieve same-service evidence first and cross-service analogies second.

    Explicit documentation-only changes do not retrieve production incident
    history; this is a small release-classification guard for the demo data.
    """
    query_text = build_release_query(release)
    documentation_only = bool(release.change_types) and set(release.change_types) <= {"documentation_only"}
    if documentation_only:
        return {"incidents": [], "runbooks": []}

    same_service_incidents = store.query(
        query_text,
        doc_type="incident",
        n_results=incident_k,
        service_filter=release.service,
    )
    global_incidents = store.query(
        query_text,
        doc_type="incident",
        n_results=max(incident_k * 2, incident_k),
    )
    incidents = _merge_service_first(
        same_service_incidents,
        global_incidents,
        limit=incident_k,
    )

    same_service_runbooks = store.query(
        query_text,
        doc_type="runbook",
        n_results=runbook_k,
        service_filter=release.service,
    )
    global_runbooks = store.query(
        query_text,
        doc_type="runbook",
        n_results=max(runbook_k * 2, runbook_k),
    )
    runbooks = _merge_service_first(
        same_service_runbooks,
        global_runbooks,
        limit=runbook_k,
    )
    return {"incidents": incidents, "runbooks": runbooks}
