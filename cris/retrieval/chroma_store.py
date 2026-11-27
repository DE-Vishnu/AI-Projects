"""Persistent ChromaDB index for incident and runbook knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RetrievedDocument:
    document: str
    metadata: dict[str, Any]
    distance: float
    cosine_similarity: float


class ChromaKnowledgeStore:
    """Small wrapper around Chroma so the rest of CRIS is DB-agnostic."""

    COLLECTION_NAME = "cris_knowledge"

    def __init__(self, persist_directory: Path) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "ChromaDB is not installed. Run: python -m pip install -r requirements.txt"
            ) from exc

        persist_directory.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_directory))
        # Chroma's default embedding function is local all-MiniLM-L6-v2 via ONNX.
        # Chroma automatically embeds documents on upsert and query text on query.
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            configuration={"hnsw": {"space": "cosine"}},
        )

    @property
    def count(self) -> int:
        return self.collection.count()

    def upsert_documents(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, str | int | float | bool]],
    ) -> None:
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("ids, documents and metadatas must have equal lengths")
        if not ids:
            return
        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def query(
        self,
        query_text: str,
        *,
        doc_type: str,
        n_results: int = 5,
        service_filter: str | None = None,
    ) -> list[RetrievedDocument]:
        if not query_text.strip():
            raise ValueError("query_text cannot be empty")
        if n_results < 1:
            raise ValueError("n_results must be at least 1")
        available = self.collection.count()
        if available == 0:
            return []

        where_filter: dict[str, Any]
        if service_filter:
            where_filter = {
                "$and": [
                    {"doc_type": doc_type},
                    {"service": service_filter},
                ]
            }
        else:
            where_filter = {"doc_type": doc_type}

        result = self.collection.query(
            query_texts=[query_text],
            n_results=min(n_results, available),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        matches: list[RetrievedDocument] = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            numeric_distance = float(distance)
            # For cosine distance, smaller is closer; 1 - distance is the
            # cosine similarity score. It is NOT a probability or calibrated %.
            cosine_similarity = 1.0 - numeric_distance
            matches.append(
                RetrievedDocument(
                    document=document,
                    metadata=metadata or {},
                    distance=numeric_distance,
                    cosine_similarity=cosine_similarity,
                )
            )
        return matches

    def reset(self) -> None:
        """Delete and recreate the collection (useful when rebuilding the demo index)."""
        self.client.delete_collection(self.COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            configuration={"hnsw": {"space": "cosine"}},
        )
