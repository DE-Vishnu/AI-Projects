"""JSON loading helpers for the local prototype dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Incident, Release


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Dataset not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def load_incidents(path: Path) -> list[Incident]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"Expected a JSON array in {path}")
    incidents = [Incident.from_dict(item) for item in raw]
    ids = [incident.incident_id for incident in incidents]
    if len(ids) != len(set(ids)):
        raise ValueError("Incident IDs must be unique")
    return incidents


def load_releases(path: Path) -> list[Release]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"Expected a JSON array in {path}")
    releases = [Release.from_dict(item) for item in raw]
    ids = [release.release_id for release in releases]
    if len(ids) != len(set(ids)):
        raise ValueError("Release IDs must be unique")
    return releases


def load_runbooks(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"Expected a JSON array in {path}")
    return raw
