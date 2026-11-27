"""Read Markdown runbooks, parse metadata and create retrieval-sized chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Runbook:
    runbook_id: str
    title: str
    service: str
    triggers: list[str]
    body: str
    source_path: str


@dataclass(frozen=True)
class RunbookChunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int | float | bool]


def load_markdown_runbook(path: Path) -> Runbook:
    """Load Markdown with YAML front matter delimited by --- lines."""
    if not path.exists():
        raise FileNotFoundError(f"Runbook not found: {path}")
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", raw, flags=re.DOTALL)
    if not match:
        raise ValueError(
            f"{path.name} must start with YAML front matter between --- lines"
        )

    metadata: Any = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    if not isinstance(metadata, dict):
        raise ValueError(f"{path.name} front matter must be a YAML object")

    runbook_id = metadata.get("runbook_id")
    title = metadata.get("title")
    service = metadata.get("service")
    triggers = metadata.get("triggers", [])
    if not all(isinstance(value, str) and value.strip() for value in (runbook_id, title, service)):
        raise ValueError(f"{path.name} must include runbook_id, title and service")
    if not isinstance(triggers, list) or any(not isinstance(item, str) for item in triggers):
        raise ValueError(f"{path.name} field 'triggers' must be a list of strings")
    if not body:
        raise ValueError(f"{path.name} has no Markdown body")

    return Runbook(
        runbook_id=runbook_id.strip(),
        title=title.strip(),
        service=service.strip(),
        triggers=[item.strip() for item in triggers if item.strip()],
        body=body,
        source_path=str(path),
    )


def load_markdown_runbooks(directory: Path) -> list[Runbook]:
    """Load all .md files in a directory in a stable order."""
    if not directory.exists():
        raise FileNotFoundError(f"Runbook directory not found: {directory}")
    paths = sorted(directory.glob("*.md"))
    runbooks = [load_markdown_runbook(path) for path in paths]
    ids = [runbook.runbook_id for runbook in runbooks]
    if len(ids) != len(set(ids)):
        raise ValueError("Runbook IDs must be unique")
    if not runbooks:
        raise ValueError(f"No Markdown runbooks found in {directory}")
    return runbooks


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split long content on paragraph/bullet boundaries with small overlap."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        # Extremely long paragraph: split on sentence boundaries as a fallback.
        pieces = [paragraph]
        if len(paragraph) > max_chars:
            pieces = re.split(r"(?<=[.!?])\s+", paragraph)

        for piece in pieces:
            if not piece:
                continue
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if len(candidate) <= max_chars:
                current = candidate
                continue

            if current:
                chunks.append(current)
                overlap = current[-overlap_chars:] if overlap_chars else ""
                current = f"{overlap}\n{piece}".strip() if overlap else piece
            else:
                # A single indivisible token/paragraph can exceed max_chars.
                for start in range(0, len(piece), max_chars - overlap_chars):
                    chunks.append(piece[start : start + max_chars])
                current = ""

    if current:
        chunks.append(current)
    return chunks


def chunk_runbook(
    runbook: Runbook,
    *,
    max_chars: int = 1_000,
    overlap_chars: int = 120,
) -> list[RunbookChunk]:
    """Split a runbook by headings, then size-limit large sections.

    Each chunk retains the section heading, parent runbook ID and source metadata.
    Character sizing is a simple hackathon approximation; production chunking
    should consider tokenizer counts and the embedding model's context window.
    """
    if max_chars < 200 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("Use max_chars >= 200 and 0 <= overlap_chars < max_chars")

    lines = runbook.body.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Overview"
    current_lines: list[str] = []

    for line in lines:
        heading_match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if heading_match:
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))

    chunks: list[RunbookChunk] = []
    chunk_number = 0
    for heading, section_lines in sections:
        section_text = "\n".join(section_lines).strip()
        if not section_text:
            continue
        sized_chunks = _split_long_text(section_text, max_chars, overlap_chars)
        for piece in sized_chunks:
            chunk_number += 1
            text = (
                f"Runbook: {runbook.title}\n"
                f"Service: {runbook.service}\n"
                f"Section: {heading}\n"
                f"Triggers: {', '.join(runbook.triggers)}\n\n"
                f"{piece}"
            )
            chunks.append(
                RunbookChunk(
                    chunk_id=f"runbook::{runbook.runbook_id}::chunk::{chunk_number:03d}",
                    text=text,
                    metadata={
                        "doc_type": "runbook",
                        "source_id": runbook.runbook_id,
                        "runbook_id": runbook.runbook_id,
                        "title": runbook.title,
                        "service": runbook.service,
                        "section": heading,
                        "chunk_index": chunk_number,
                        "source_file": Path(runbook.source_path).name,
                        "triggers": ",".join(runbook.triggers),
                    },
                )
            )
    return chunks


def chunk_all_runbooks(
    runbooks: list[Runbook], *, max_chars: int = 1_000, overlap_chars: int = 120
) -> list[RunbookChunk]:
    all_chunks: list[RunbookChunk] = []
    for runbook in runbooks:
        all_chunks.extend(
            chunk_runbook(runbook, max_chars=max_chars, overlap_chars=overlap_chars)
        )
    return all_chunks
