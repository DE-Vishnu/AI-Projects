# Continuous Release Intelligence System (CRIS)

CRIS is a local hackathon prototype that assesses proposed releases using historical incidents, runbooks, current service health and an LLM-generated evidence-grounded explanation. It combines deterministic risk scoring, ChromaDB semantic retrieval and a LangGraph workflow, with a Streamlit dashboard.

> **Prototype boundary:** all incident, release, runbook and monitoring data included here is synthetic and local. Jira, Confluence, GitHub, Azure DevOps, New Relic, Datadog and Prometheus are future connectors—not live integrations. This is a decision-support demo, not an automatic production deployment gate.

## What is implemented

### Day 1 — deterministic risk foundation
- Typed Incident and Release models with input validation.
- 15 synthetic incident records, 3 release scenarios and 5 sample runbooks.
- Explainable risk scoring across historical incident evidence, change sensitivity, blast radius, operational health and release readiness.

### Day 2 — knowledge ingestion and retrieval
- JSON/CSV incident ingestion into a common Incident model.
- Markdown runbook parsing using YAML front matter.
- Heading-aware runbook chunking with source metadata.
- Persistent ChromaDB collection containing incident documents and runbook chunks.
- Local `all-MiniLM-L6-v2` embeddings through Chroma's default embedding function.
- Semantic retrieval of incidents and runbook sections.
- Timestamped mock monitoring adapter with a configurable freshness window and retrieval evaluation cases.

### Day 3 — end-to-end CRIS workflow
- LangGraph workflow: load release → retrieve evidence → load service health → calculate risk → generate analysis.
- Seven telemetry fields are mapped from the latest mock health snapshot into the deterministic risk calculation.
- Historical risk is calculated from the incidents returned by ChromaDB for that release—not by scoring the full incident file. The historical signal blends Chroma semantic relevance (60%), structured field overlap (40%) and a historical-severity multiplier. These are visible, illustrative prototype weights.
- LLM adapter uses an OpenAI-compatible Chat Completions endpoint, configurable by environment variables.
- The prompt carries the release, risk breakdown, health snapshot and retrieved evidence to the model.
- Retrieval prefers same-service incident/runbook chunks first, then adds unique cross-service analogies. The explicit documentation-only sample release skips production incident/runbook retrieval.
- LLM output is parsed and its evidence IDs are restricted to IDs actually retrieved by CRIS.
- If no LLM is configured, the app uses a clearly labelled deterministic demo summary. It does not claim that an LLM was called.
- Streamlit dashboard displays risk, health, evidence, recommendations and workflow trace.

## Requirements

- Python 3.10 or newer (tested design target: Python 3.13).
- Internet access on the first Chroma embedding-model run so the local embedding model can be downloaded and cached.
- An API key and model name for live LLM generation, unless using a local OpenAI-compatible endpoint.

## Windows setup (PowerShell)

Open PowerShell in the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Build the Chroma knowledge base (repeat after changing incident or runbook source files):

```powershell
.\.venv\Scripts\python.exe -m cris.day2 index --reset
```

Run a complete end-to-end assessment in deterministic demo mode (no LLM call):

```powershell
.\.venv\Scripts\python.exe -m cris.assess --release REL-2026-041 --demo-mode
```

Run the interactive dashboard:

```powershell
.\.venv\Scripts\python.exe -m streamlit run cris/app.py
```

The dashboard provides the full assessment flow. If no LLM is configured, it visibly marks the output as demo mode.

## Configure a live LLM

Copy `.env.example` to `.env` in the project root. For this OpenAI-backed prototype, use the following values:

```text
CRIS_LLM_BASE_URL=https://api.openai.com/v1
CRIS_LLM_API_KEY=your_openai_api_key
CRIS_LLM_MODEL=gpt-6-luna
CRIS_LLM_TIMEOUT_SECONDS=60
CRIS_MONITORING_MAX_AGE_MINUTES=1440
```

The adapter sends a request to `<CRIS_LLM_BASE_URL>/chat/completions` and requests a JSON response. The recommended `gpt-6-luna` model is listed by OpenAI as a low-cost focused-task model and supports Chat Completions and structured outputs. The model setting can be changed to another compatible model. For a local endpoint, the API key may be omitted if the base URL uses `localhost` or `127.0.0.1`.

After each live call, CRIS displays the input/output token counts returned by the API. The dashboard does not need the key pasted into the UI; keep it only in the ignored local `.env` file.

Do not commit `.env` or paste API keys into source files. A ChatGPT subscription and API access are separate products; use an API credential approved for your hackathon environment. Check your provider's model name, endpoint, rate limits and data handling terms.

The live model is asked to return JSON containing an executive summary, key risks, checks, rollback triggers, a suggested review posture and unknowns. The app validates source citations against retrieved evidence. A guardrail prevents the LLM from recommending a less cautious action than the deterministic risk band requires. These controls reduce, but do not eliminate, hallucination risk.

## Commands

```powershell
# Inspect sample monitoring data
.\.venv\Scripts\python.exe -m cris.day2 health --service orders_ingestion

# Retrieve semantic evidence
.\.venv\Scripts\python.exe -m cris.day2 retrieve --release REL-2026-041

# Evaluate retrieval quality
.\.venv\Scripts\python.exe -m cris.day2 eval

# Run all automated tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Risk model notes

The risk score is a prioritization index, not a probability of failure. The historical dimension uses only ChromaDB-retrieved incident candidates. For each candidate, the prototype combines semantic relevance (60%) and structured field overlap (40%), then applies a severity multiplier (SEV1 1.00, SEV2 0.90, SEV3 0.80, SEV4 0.70; unknown 0.85). The strongest candidate determines the historical dimension so that multiple similar incidents do not simply add together. These values, the five dimension weights and operational thresholds are illustrative prototype assumptions; they must be calibrated against reviewed deployment history before production use. Current health comes from synthetic timestamped JSON snapshots; it is not live telemetry.

## Security and data handling

Use only synthetic or approved anonymized data. Do not send confidential incident tickets, customer information, source code, production logs or runbooks to an external LLM or embedding provider without company approval. The Chroma index is local, but a configured remote LLM provider receives the prompt context and retrieved evidence.

## Future production connectors

- Incident management: Jira Service Management / ServiceNow APIs.
- Runbooks: Confluence / SharePoint / Git repositories.
- Release metadata: GitHub / Azure DevOps pull requests and CI/CD events.
- Observability: New Relic / Datadog / Prometheus APIs.
- Production hardening: stronger identity and access controls, secrets management, audit logs, stale-telemetry detection, retrieval evaluation, model evaluation, feedback capture and human approval controls.
