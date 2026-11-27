"""Run one end-to-end CRIS assessment from the terminal."""
from __future__ import annotations

import argparse
from pathlib import Path

from .llm import LLMConfig
from .workflow.assessment import run_assessment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a complete CRIS release assessment")
    parser.add_argument("--release", required=True, help="Release ID from data/releases.json")
    parser.add_argument("--demo-mode", action="store_true", help="Do not call an LLM; use deterministic demo output")
    parser.add_argument("--store", default=str(PROJECT_ROOT / "storage" / "chroma"))
    args = parser.parse_args()

    config = LLMConfig.from_environment()
    result = run_assessment(
        args.release,
        PROJECT_ROOT,
        chroma_dir=Path(args.store),
        llm_enabled=not args.demo_mode,
        llm_config=config,
    )
    risk = result["risk_assessment"]
    print(f"\nCRIS assessment: {risk.release_id} — {risk.release_name}")
    print(f"Risk: {risk.total_score}/100 ({risk.risk_band})")
    print(f"Mode: {result['analysis_mode']}")
    usage = result["ai_analysis"].get("token_usage")
    if usage and usage.get("total_tokens") is not None:
        print(f"LLM token usage: {usage['total_tokens']} total "
              f"({usage.get('prompt_tokens') or 0} input / {usage.get('completion_tokens') or 0} output)")
    print(f"\n{result['ai_analysis']['executive_summary']}")
    print(f"\nSuggested decision: {result['ai_analysis']['release_recommendation']}")
    print("\nKey risks:")
    for item in result["ai_analysis"].get("key_risks", []):
        refs = ", ".join(item.get("evidence_ids", []))
        print(f"- {item['risk']} | Evidence: {refs or 'not cited'}")
        print(f"  {item['why_it_matters']}")
    print("\nRecommended checks:")
    for item in result["ai_analysis"].get("recommended_checks", []):
        refs = ", ".join(item.get("evidence_ids", []))
        print(f"- {item['action']} | Evidence: {refs or 'not cited'}")
        print(f"  {item['reason']}")
    print("\nCaveats / unknowns:")
    for item in result["ai_analysis"].get("unknowns", []):
        print(f"- {item}")


if __name__ == "__main__":
    main()
