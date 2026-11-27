"""Run the Day 1 CRIS risk assessment from the command line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data_loader import load_incidents, load_releases
from .scoring import assess_release

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess release risk using the local incident history.")
    parser.add_argument("--release", help="Release ID from data/releases.json")
    parser.add_argument("--json", action="store_true", help="Print the full assessment as JSON")
    args = parser.parse_args()

    incidents = load_incidents(PROJECT_ROOT / "data" / "incidents.json")
    releases = load_releases(PROJECT_ROOT / "data" / "releases.json")
    if args.release:
        selected = [release for release in releases if release.release_id.casefold() == args.release.casefold()]
        if not selected:
            available = ", ".join(r.release_id for r in releases)
            parser.error(f"Unknown release '{args.release}'. Available releases: {available}")
        releases = selected

    for release in releases:
        report = assess_release(release, incidents)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
            continue
        print("=" * 76)
        print(f"{report.release_id} | {report.release_name}")
        print(f"RISK: {report.risk_band.upper()} — {report.total_score}/100")
        print(f"Operational evidence coverage: {report.evidence_coverage_pct}% "
              f"({report.available_operational_signals}/{report.total_operational_signals} signals)")
        print("\nRisk breakdown:")
        for dimension in report.dimensions:
            print(f"  - {dimension.label}: {dimension.score:g}/{dimension.max_score:g}")
            for item in dimension.evidence[:2]:
                print(f"      • {item}")
        print("\nRelevant historical incidents:")
        if report.matched_incidents:
            for match in report.matched_incidents:
                print(f"  - {match.incident_id} | {match.title} | {match.similarity_pct:g}% match")
                print(f"      Root cause: {match.root_cause}")
        else:
            print("  - No strong matches in the sample incident history.")
        print("\nRecommended preventive actions:")
        for recommendation in report.recommendations:
            print(f"  - {recommendation}")
        print("\nCaveats:")
        for caveat in report.caveats:
            print(f"  - {caveat}")
        print()


if __name__ == "__main__":
    main()
