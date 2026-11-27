"""Day 2 commands: index the knowledge base, retrieve evidence and inspect health."""

from __future__ import annotations

import argparse
from pathlib import Path

from .data_loader import load_releases
from .ingestion.monitoring import JsonMonitoringSource
from .retrieval.chroma_store import ChromaKnowledgeStore
from .retrieval.indexer import index_knowledge
from .retrieval.evaluation import evaluate_retrieval, load_evaluation_cases
from .retrieval.release_search import retrieve_release_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _index_command(args: argparse.Namespace) -> None:
    result = index_knowledge(
        incident_source=Path(args.incidents),
        runbook_directory=Path(args.runbooks),
        persist_directory=Path(args.store),
        reset=args.reset,
    )
    print("\nCRIS knowledge-base indexing complete")
    for key, value in result.items():
        print(f"  {key.replace('_', ' ').title()}: {value}")
    print(f"  Persistent store: {Path(args.store).resolve()}")


def _retrieve_command(args: argparse.Namespace) -> None:
    releases = load_releases(PROJECT_ROOT / "data" / "releases.json")
    selected = next(
        (release for release in releases if release.release_id.casefold() == args.release.casefold()),
        None,
    )
    if selected is None:
        available = ", ".join(release.release_id for release in releases)
        raise SystemExit(f"Unknown release '{args.release}'. Available: {available}")

    store = ChromaKnowledgeStore(Path(args.store))
    evidence = retrieve_release_evidence(
        selected, store, incident_k=args.incident_k, runbook_k=args.runbook_k
    )
    print(f"\nSemantic evidence for {selected.release_id}: {selected.name}")
    print("\nMOST RELEVANT HISTORICAL INCIDENTS")
    _print_results(evidence["incidents"])
    print("\nMOST RELEVANT RUNBOOK SECTIONS")
    _print_results(evidence["runbooks"])


def _print_results(results) -> None:
    if not results:
        print("  No results found. Run the index command first.")
        return
    for rank, result in enumerate(results, start=1):
        metadata = result.metadata
        source_id = metadata.get("source_id", "unknown")
        title = metadata.get("title", metadata.get("section", "Untitled"))
        print(
            f"  {rank}. {source_id} | {title} | "
            f"cosine similarity score: {result.cosine_similarity:.3f} (not a probability)"
        )
        print(f"     Service: {metadata.get('service', 'unknown')}")
        preview = " ".join(result.document.split())
        print(f"     Evidence: {preview[:380]}{'...' if len(preview) > 380 else ''}")


def _eval_command(args: argparse.Namespace) -> None:
    releases = load_releases(PROJECT_ROOT / "data" / "releases.json")
    cases = load_evaluation_cases(Path(args.cases))
    store = ChromaKnowledgeStore(Path(args.store))
    reports = evaluate_retrieval(cases, releases, store, k=args.k)
    print(f"\nRetrieval evaluation — Recall@{args.k}")
    for report in reports:
        print(f"\n{report['release_id']} | {report['purpose']}")
        if report["manual_review_required"]:
            print("  Negative control: manually inspect returned neighbours; no relevance IDs were pre-labelled.")
        else:
            print(f"  Incident recall@{args.k}: {report['incident_recall_at_k']}")
            print(f"  Runbook recall@{args.k}: {report['runbook_recall_at_k']}")
        print(f"  Retrieved incidents: {', '.join(report['retrieved_incident_ids']) or 'none'}")
        print(f"  Retrieved runbooks: {', '.join(report['retrieved_runbook_ids']) or 'none'}")


def _health_command(args: argparse.Namespace) -> None:
    source = JsonMonitoringSource(Path(args.file))
    snapshot = source.latest_snapshot(args.service)
    if snapshot is None:
        print(f"No monitoring snapshot found for service: {args.service}")
        return
    print(f"\nMonitoring snapshot for {snapshot.service}")
    print(f"  Captured at: {snapshot.captured_at.isoformat()}")
    print(f"  Source: {snapshot.source}")
    print("  Metrics:")
    for name, value in snapshot.metrics.items():
        display = "UNKNOWN" if value is None else value
        print(f"    - {name}: {display}")
    print("\nNote: this is an independent health snapshot; it is not stored inside the release record.")


def main() -> None:
    parser = argparse.ArgumentParser(description="CRIS Day 2: ingestion, vector retrieval and monitoring adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Ingest incidents/runbooks and build the Chroma index")
    index_parser.add_argument("--incidents", default=str(PROJECT_ROOT / "data" / "incidents.json"))
    index_parser.add_argument("--runbooks", default=str(PROJECT_ROOT / "data" / "runbooks"))
    index_parser.add_argument("--store", default=str(PROJECT_ROOT / "storage" / "chroma"))
    index_parser.add_argument("--reset", action="store_true", help="Delete the previous collection before indexing")
    index_parser.set_defaults(func=_index_command)

    retrieve_parser = subparsers.add_parser("retrieve", help="Retrieve similar incidents and runbook sections for a release")
    retrieve_parser.add_argument("--release", required=True, help="Release ID from data/releases.json")
    retrieve_parser.add_argument("--store", default=str(PROJECT_ROOT / "storage" / "chroma"))
    retrieve_parser.add_argument("--incident-k", type=int, default=4)
    retrieve_parser.add_argument("--runbook-k", type=int, default=4)
    retrieve_parser.set_defaults(func=_retrieve_command)

    eval_parser = subparsers.add_parser("eval", help="Evaluate retrieval against hand-labelled release scenarios")
    eval_parser.add_argument("--cases", default=str(PROJECT_ROOT / "data" / "retrieval_eval.json"))
    eval_parser.add_argument("--store", default=str(PROJECT_ROOT / "storage" / "chroma"))
    eval_parser.add_argument("-k", type=int, default=4)
    eval_parser.set_defaults(func=_eval_command)

    health_parser = subparsers.add_parser("health", help="Read the latest mock health snapshot for a service")
    health_parser.add_argument("--service", required=True)
    health_parser.add_argument("--file", default=str(PROJECT_ROOT / "data" / "monitoring" / "health_snapshots.json"))
    health_parser.set_defaults(func=_health_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
