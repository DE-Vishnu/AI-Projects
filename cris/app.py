"""Streamlit dashboard for the Continuous Release Intelligence System."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from cris.data_loader import load_releases
from cris.llm import LLMConfig
from cris.workflow.assessment import run_assessment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    st.set_page_config(page_title="CRIS | Continuous Release Intelligence", page_icon="🛡️", layout="wide")
    st.title("Continuous Release Intelligence System")
    st.caption("Assess release risk using historical incidents, runbooks and current service health.")

    releases = load_releases(PROJECT_ROOT / "data" / "releases.json")
    labels = {f"{r.release_id} — {r.name}": r.release_id for r in releases}
    selected_label = st.selectbox("Select a release to assess", list(labels))
    selected_release_id = labels[selected_label]

    config = LLMConfig.from_environment()
    with st.sidebar:
        st.header("Assessment configuration")
        st.write("**LLM provider:**", "Configured" if config.is_configured else "Not configured")
        if config.is_configured:
            st.caption(f"Model: {config.model}")
            st.success("Live LLM analysis is ready. API key is loaded from your local .env file.")
        else:
            st.info("Add your OpenAI API key to the local .env file to enable live analysis. The app will otherwise use a clearly labelled demo summary.")
        st.caption("Data source: local synthetic JSON, Markdown and ChromaDB.")
        run_llm = st.checkbox("Use configured LLM", value=config.is_configured, disabled=not config.is_configured)
        st.warning("Prototype only. Do not use as an automatic production deployment gate.")

    if st.button("Assess release", type="primary", use_container_width=True):
        with st.spinner("Loading evidence, checking service health and assessing release..."):
            try:
                result = run_assessment(
                    selected_release_id,
                    PROJECT_ROOT,
                    llm_enabled=run_llm,
                )
                st.session_state["cris_last_result"] = result
            except Exception as exc:
                st.error(f"Assessment could not be completed: {exc}")
                st.stop()

    result = st.session_state.get("cris_last_result")
    if not result:
        st.info("Select a release and click **Assess release** to see the end-to-end assessment.")
        st.markdown("### What the workflow does")
        st.markdown("1. Load the release details.\n2. Retrieve relevant incidents and runbook sections from ChromaDB.\n3. Load the latest available service-health snapshot.\n4. Calculate an explainable risk score using only the incidents retrieved for this release, plus change sensitivity, blast radius, health and readiness.\n5. Generate an evidence-grounded LLM assessment, or a clearly labelled demo summary if no LLM is configured.")
        return

    release = result["release"]
    risk = result["risk_assessment"]
    evidence = result["evidence"]
    analysis = result["ai_analysis"]
    health = result.get("health_payload")

    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Risk score", f"{risk.total_score}/100")
    col2.metric("Risk classification", risk.risk_band)
    col3.metric("Operational coverage", f"{risk.evidence_coverage_pct}%")
    col4.metric("Retrieved evidence", f"{len(evidence['incidents']) + len(evidence['runbooks'])}")
    st.caption(f"Analysis mode: {result.get('analysis_mode', 'Unknown')} · Release: {release.release_id}")

    if risk.risk_band in {"Critical", "High"}:
        st.error("Elevated release risk. Review the evidence and preventive checks before deployment.")
    else:
        st.success("No high-risk signal in the current prototype assessment. Follow normal release controls.")

    left, right = st.columns([1.05, 1])
    with left:
        st.subheader("Risk breakdown")
        rows = [{"Dimension": d.label, "Risk points": d.score, "Maximum": d.max_score} for d in risk.dimensions]
        st.dataframe(rows, hide_index=True, use_container_width=True)
        history_dimension = next((d for d in risk.dimensions if d.key == "historical_similarity"), None)
        if history_dimension:
            st.caption(history_dimension.explanation)
            for item in history_dimension.evidence:
                st.caption(f"• {item}")
        st.subheader("Current service health")
        if health:
            st.caption(f"Source: {health['source']} · Captured: {health['captured_at']} · Age: {health.get('age_minutes', 'unknown')} min")
            if health.get("status") == "stale":
                st.warning("This monitoring snapshot is stale and was excluded from operational risk scoring.")
            st.dataframe(
                [{"Metric": name, "Value": "UNKNOWN" if value is None else value} for name, value in health["metrics"].items()],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.warning("No monitoring snapshot found for this service.")
    with right:
        st.subheader("AI release intelligence")
        st.markdown(analysis.get("executive_summary", "No summary returned."))
        st.markdown(f"**Suggested decision:** `{analysis.get('release_recommendation', 'HOLD_FOR_REVIEW')}`")
        if analysis.get("recommendation_note"):
            st.warning(analysis["recommendation_note"])
        token_usage = analysis.get("token_usage")
        if token_usage and token_usage.get("total_tokens") is not None:
            st.caption(
                f"LLM usage: {token_usage['total_tokens']:,} tokens "
                f"({token_usage.get('prompt_tokens') or 0:,} input / "
                f"{token_usage.get('completion_tokens') or 0:,} output) · "
                f"Model: {token_usage.get('model', config.model)}"
            )
        if analysis.get("key_risks"):
            st.markdown("**Key risks**")
            for row in analysis["key_risks"]:
                refs = ", ".join(row.get("evidence_ids", [])) or "No validated source reference"
                st.markdown(f"- **{row['risk']}** — {row['why_it_matters']}  \n  Evidence: `{refs}`")
        if analysis.get("recommended_checks"):
            st.markdown("**Recommended checks**")
            for row in analysis["recommended_checks"]:
                refs = ", ".join(row.get("evidence_ids", [])) or "Review engineering runbook"
                st.markdown(f"- **{row['action']}** — {row['reason']}  \n  Source: `{refs}`")
        if analysis.get("rollback_triggers"):
            st.markdown("**Rollback triggers**")
            for row in analysis["rollback_triggers"]:
                st.markdown(f"- {row['trigger']} (source: `{row.get('source_id') or 'not cited'}`)")
        if analysis.get("unknowns"):
            with st.expander("Unknowns and caveats", expanded=True):
                for item in analysis["unknowns"]:
                    st.write(f"- {item}")

    st.subheader("Retrieved historical evidence")
    incident_tab, runbook_tab = st.tabs(["Incidents", "Runbook sections"])
    with incident_tab:
        if not evidence["incidents"]:
            st.info("No incident records were retrieved. This may be expected for a documentation-only change.")
        for item in evidence["incidents"]:
            meta = item.metadata or {}
            title = meta.get("title", meta.get("source_id", "Incident"))
            st.markdown(f"**{meta.get('source_id', 'Unknown')} — {title}** · similarity {item.cosine_similarity:.3f}")
            st.caption(f"Service: {meta.get('service', 'unknown')} · Severity: {meta.get('severity', 'unknown')}")
            st.write(item.document)
            st.divider()
    with runbook_tab:
        if not evidence["runbooks"]:
            st.info("No runbook sections were retrieved for this release.")
        for item in evidence["runbooks"]:
            meta = item.metadata or {}
            st.markdown(f"**{meta.get('source_id', 'Unknown')} — {meta.get('section', meta.get('title', 'Runbook'))}** · similarity {item.cosine_similarity:.3f}")
            st.caption(f"Service: {meta.get('service', 'unknown')} · Source: {meta.get('source_file', 'local runbook')}")
            st.write(item.document)
            st.divider()

    with st.expander("Workflow execution trace"):
        for step in result.get("workflow_steps", []):
            st.write(f"✓ {step}")
    with st.expander("Raw assessment JSON"):
        st.code(json.dumps({
            "release_id": risk.release_id,
            "risk_assessment": risk.to_dict(),
            "analysis": analysis,
        }, indent=2, default=str), language="json")


if __name__ == "__main__":
    main()
