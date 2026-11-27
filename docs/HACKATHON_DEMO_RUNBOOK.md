# CRIS hackathon demo runbook

## Before the demo

1. Extract the project ZIP and open the project root in VS Code.
2. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   If this is a fresh folder without `.venv`, create it first with `python -m venv .venv`.

3. Build the local knowledge base once:

   ```powershell
   .\.venv\Scripts\python.exe -m cris.day2 index --reset
   ```

4. Verify tests:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -v
   ```

5. Enable live LLM: copy `.env.example` to `.env`, paste your OpenAI API key into `CRIS_LLM_API_KEY`, and keep `CRIS_LLM_MODEL=gpt-6-luna`. Never display or commit `.env`.

## Start the application

```powershell
.\.venv\Scripts\python.exe -m streamlit run cris\app.py
```

The browser opens the CRIS dashboard.

## Recommended demo sequence

1. Select `REL-2026-041 — Orders incremental ingestion and MERGE update`.
2. Click **Assess release**.
3. Show the deterministic risk score and the five scoring dimensions. Explain that historical risk uses ChromaDB-retrieved incidents only and blends semantic relevance, field overlap and incident severity.
4. Show the latest orders service health snapshot and its timestamp/source.
5. Show retrieved evidence: INC-1042, INC-1018 and relevant RB-ORD-01 sections.
6. Show the LLM-generated explanation and preventive checks if a live provider is configured. Otherwise point out the explicit demo-mode label.
7. Select `REL-2026-042`, the documentation-only release, and show that production incident/runbook retrieval is skipped.
8. Optionally select `REL-2026-043` to show the payment scenario.

## Be accurate in the pitch

- The incident, release, runbook and monitoring data are synthetic.
- The monitoring adapter reads local snapshots; it is not a live New Relic/Datadog connection.
- The LLM is called only when provider credentials/model are configured. Demo mode is deterministic and not an LLM response.
- ChromaDB retrieval is semantic search, not proof that an incident will occur.
- The risk score is a prioritization index, not a failure probability.
- The prototype supports human review; it does not automatically block or deploy releases.
