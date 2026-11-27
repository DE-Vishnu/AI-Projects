"""Typed data models for CRIS Day 1 prototype.

The project intentionally uses only the Python standard library on Day 1 so it
can be run without API keys, network access, or package installation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DataValidationError(ValueError):
    """Raised when a JSON record does not satisfy the expected data contract."""


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"Field '{key}' must be a non-empty string")
    return value.strip()


def _string_list(data: dict[str, Any], key: str, *, required: bool = False) -> list[str]:
    value = data.get(key, [])
    if value is None and not required:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise DataValidationError(f"Field '{key}' must be a list of non-empty strings")
    return [item.strip() for item in value]


@dataclass(frozen=True)
class Incident:
    incident_id: str
    title: str
    service: str
    severity: str
    change_types: list[str]
    affected_components: list[str]
    trigger_keywords: list[str]
    root_cause: str
    impact: str
    resolution: str
    prevention: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Incident":
        return cls(
            incident_id=_required_str(data, "incident_id"),
            title=_required_str(data, "title"),
            service=_required_str(data, "service"),
            severity=_required_str(data, "severity").lower(),
            change_types=_string_list(data, "change_types", required=True),
            affected_components=_string_list(data, "affected_components"),
            trigger_keywords=_string_list(data, "trigger_keywords"),
            root_cause=_required_str(data, "root_cause"),
            impact=_required_str(data, "impact"),
            resolution=_required_str(data, "resolution"),
            prevention=_string_list(data, "prevention"),
        )


@dataclass(frozen=True)
class Release:
    release_id: str
    name: str
    service: str
    description: str
    change_types: list[str]
    changed_components: list[str]
    downstream_dependencies: list[str]
    criticality: str
    test_status: str
    rollback_tested: bool
    canary_enabled: bool
    approvals_complete: bool
    operational_signals: dict[str, float | None] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Release":
        signals = data.get("operational_signals", {})
        if not isinstance(signals, dict):
            raise DataValidationError("Field 'operational_signals' must be an object")
        clean_signals: dict[str, float | None] = {}
        allowed_signals = {
            "error_rate_pct", "latency_p95_ms", "pipeline_lag_minutes",
            "cpu_utilization_pct", "memory_utilization_pct",
            "job_failure_rate_pct", "data_freshness_lag_minutes",
        }
        for key, value in signals.items():
            if key not in allowed_signals:
                raise DataValidationError(f"Unsupported operational signal: {key}")
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise DataValidationError(f"Operational signal '{key}' must be numeric or null")
            clean_signals[key] = float(value) if value is not None else None

        for flag in ("rollback_tested", "canary_enabled", "approvals_complete"):
            if not isinstance(data.get(flag), bool):
                raise DataValidationError(f"Field '{flag}' must be boolean")

        return cls(
            release_id=_required_str(data, "release_id"),
            name=_required_str(data, "name"),
            service=_required_str(data, "service"),
            description=_required_str(data, "description"),
            change_types=_string_list(data, "change_types", required=True),
            changed_components=_string_list(data, "changed_components"),
            downstream_dependencies=_string_list(data, "downstream_dependencies"),
            criticality=_required_str(data, "criticality").lower(),
            test_status=_required_str(data, "test_status").lower(),
            rollback_tested=data["rollback_tested"],
            canary_enabled=data["canary_enabled"],
            approvals_complete=data["approvals_complete"],
            operational_signals=clean_signals,
        )
