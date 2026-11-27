"""Convert normalized incidents and Markdown runbooks into Chroma records."""

from __future__ import annotations

from pathlib import Path

from ..ingestion.incidents import (
    incident_metadata,
    incident_to_document,
    load_incidents_from_source,
)
from ..ingestion.runbooks import chunk_all_runbooks, load_markdown_runbooks
from .chroma_store import ChromaKnowledgeStore


def index_knowledge(
    *,
    incident_source: Path,
    runbook_directory: Path,
    persist_directory: Path,
    reset: bool = False,
) -> dict[str, int]:
    incidents = load_incidents_from_source(incident_source)
    runbooks = load_markdown_runbooks(runbook_directory)
    chunks = chunk_all_runbooks(runbooks)

    store = ChromaKnowledgeStore(persist_directory)
    if reset:
        store.reset()

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for incident in incidents:
        ids.append(f"incident::{incident.incident_id}")
        documents.append(incident_to_document(incident))
        metadatas.append(incident_metadata(incident))

    for chunk in chunks:
        ids.append(chunk.chunk_id)
        documents.append(chunk.text)
        metadatas.append(chunk.metadata)

    store.upsert_documents(ids=ids, documents=documents, metadatas=metadatas)
    return {
        "incidents_loaded": len(incidents),
        "runbooks_loaded": len(runbooks),
        "runbook_chunks_created": len(chunks),
        "documents_upserted": len(ids),
        "collection_total": store.count,
    }
