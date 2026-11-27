"""Monitoring source abstraction and a local JSON-backed mock connector."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class HealthSnapshot:
    service: str
    captured_at: datetime
    source: str
    metrics: dict[str, float | None]

    @classmethod
    def from_dict(cls, data: dict) -> "HealthSnapshot":
        service = data.get("service")
        source = data.get("source")
        timestamp_text = data.get("captured_at")
        metrics = data.get("metrics")
        if not isinstance(service, str) or not service.strip():
            raise ValueError("Health snapshot requires a non-empty service")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Health snapshot requires a non-empty source")
        if not isinstance(timestamp_text, str):
            raise ValueError("Health snapshot requires an ISO-8601 captured_at")
        try:
            captured_at = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid health timestamp: {timestamp_text}") from exc
        if captured_at.tzinfo is None:
            raise ValueError("captured_at must include a timezone, for example +05:30 or Z")
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError("Health snapshot metrics must be a non-empty object")

        clean_metrics: dict[str, float | None] = {}
        for name, value in metrics.items():
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise ValueError(f"Metric '{name}' must be numeric or null")
            if value is not None and value < 0:
                raise ValueError(f"Metric '{name}' cannot be negative")
            clean_metrics[name] = float(value) if value is not None else None

        return cls(
            service=service.strip(),
            captured_at=captured_at,
            source=source.strip(),
            metrics=clean_metrics,
        )


class MonitoringSource(Protocol):
    """Interface that future New Relic/Datadog/Prometheus adapters will implement."""

    def latest_snapshot(self, service: str) -> HealthSnapshot | None:
        """Return the latest health snapshot for a service, if one exists."""
        ...


class JsonMonitoringSource:
    """Mock monitoring connector backed by timestamped JSON snapshots."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.exists():
            raise FileNotFoundError(f"Monitoring snapshots not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid monitoring JSON in {path}: {exc}") from exc
        if not isinstance(raw, list):
            raise ValueError("Monitoring snapshot file must contain a JSON array")
        self.snapshots = [HealthSnapshot.from_dict(item) for item in raw]

    def latest_snapshot(self, service: str) -> HealthSnapshot | None:
        candidates = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.service.casefold() == service.casefold()
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda snapshot: snapshot.captured_at)
