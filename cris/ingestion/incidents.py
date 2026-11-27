"""Load incident records from JSON or CSV and normalize them to Incident models."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..models import Incident
from ..data_loader import load_incidents

LIST_FIELDS = {
    "change_types",
    "affected_components",
    "trigger_keywords",
    "prevention",
}


def _parse_csv_list(value: str | None, field_name: str) -> list[str]:
    """Parse a JSON-encoded list from one CSV cell.

    Example CSV cell: ["watermark_change", "merge_logic"]
    JSON arrays are used instead of comma-splitting so values containing commas
    remain unambiguous.
    """
    if value is None or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"CSV field '{field_name}' must contain a JSON array; got {value!r}"
        ) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ValueError(f"CSV field '{field_name}' must contain a JSON array of strings")
    return [item.strip() for item in parsed if item.strip()]


def load_incidents_csv(path: Path) -> list[Incident]:
    """Read incident rows from CSV and validate them using Incident.from_dict."""
    if not path.exists():
        raise FileNotFoundError(f"Incident CSV not found: {path}")

    incidents: list[Incident] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required_columns = {
            "incident_id", "title", "service", "severity", "root_cause",
            "impact", "resolution",
        }
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Incident CSV is missing required columns: {sorted(missing)}")

        for row_number, row in enumerate(reader, start=2):
            record: dict[str, Any] = dict(row)
            for field_name in LIST_FIELDS:
                record[field_name] = _parse_csv_list(row.get(field_name), field_name)
            try:
                incidents.append(Incident.from_dict(record))
            except Exception as exc:
                raise ValueError(f"Invalid incident CSV row {row_number}: {exc}") from exc

    _validate_unique_ids(incidents)
    return incidents


def _validate_unique_ids(incidents: list[Incident]) -> None:
    ids = [incident.incident_id for incident in incidents]
    if len(ids) != len(set(ids)):
        raise ValueError("Incident IDs must be unique within the source")


def load_incidents_from_source(path: Path) -> list[Incident]:
    """Select a JSON or CSV loader based on the file extension."""
    suffix = path.suffix.casefold()
    if suffix == ".json":
        incidents = load_incidents(path)
    elif suffix == ".csv":
        incidents = load_incidents_csv(path)
    else:
        raise ValueError("Unsupported incident source. Use .json or .csv")
    _validate_unique_ids(incidents)
    return incidents


def incident_to_document(incident: Incident) -> str:
    """Turn structured incident fields into a readable search document.

    The embedding model sees this text. Keep it factual and preserve key terms
    that engineers may use when searching for similar production failures.
    """
    prevention_text = "; ".join(incident.prevention) or "Not documented"
    return "\n".join(
        [
            f"Historical production incident: {incident.incident_id}",
            f"Title: {incident.title}",
            f"Service: {incident.service}",
            f"Severity: {incident.severity}",
            f"Triggering change types: {', '.join(incident.change_types)}",
            f"Affected components: {', '.join(incident.affected_components)}",
            f"Trigger keywords: {', '.join(incident.trigger_keywords)}",
            f"Root cause: {incident.root_cause}",
            f"Production impact: {incident.impact}",
            f"Resolution: {incident.resolution}",
            f"Prevention lessons: {prevention_text}",
        ]
    )


def incident_metadata(incident: Incident) -> dict[str, str | int | float | bool]:
    """Return Chroma-compatible scalar metadata for one incident."""
    return {
        "doc_type": "incident",
        "source_id": incident.incident_id,
        "incident_id": incident.incident_id,
        "title": incident.title,
        "service": incident.service,
        "severity": incident.severity,
        "change_types": ",".join(incident.change_types),
        "components": ",".join(incident.affected_components),
    }
