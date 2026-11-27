# Day 3 — End-to-end workflow and grounded LLM analysis

## Workflow overview

The LangGraph state graph runs five nodes in sequence:

1. `load_release`: read the selected release and normalize the incident source.
2. `retrieve_evidence`: query ChromaDB for incident and runbook evidence. Same-service matches are prioritised; unique cross-service analogies can fill remaining slots. The explicit documentation-only demo release skips production-history retrieval.
3. `load_monitoring`: get the latest health snapshot for the release's service.
4. `score_release`: copy supported health fields into the release and calculate the five risk dimensions. The historical dimension uses only the incidents returned by ChromaDB, not the full incident file.
5. `generate_analysis`: call a configured LLM, or generate an explicitly labelled deterministic demo summary if no LLM is configured.

LangGraph nodes read a shared state and return partial state updates. The graph is compiled before it is invoked.

## Monitoring integration

The latest monitoring snapshot remains a separate object with its own timestamp and source. The workflow maps these seven metric names into the deterministic operational-health dimension:

- `error_rate_pct`
- `latency_p95_ms`
- `pipeline_lag_minutes`
- `cpu_utilization_pct`
- `memory_utilization_pct`
- `job_failure_rate_pct`
- `data_freshness_lag_minutes`

The current thresholds and weights are only demo assumptions. The mock JSON source is not live New Relic or Datadog data. A freshness window (`CRIS_MONITORING_MAX_AGE_MINUTES`, default 1440 for this demo) marks old snapshots stale and excludes them from the score. A production connector should use a much tighter window appropriate to each service, plus metric units, query windows, baselines and missing-data behaviour.

## LLM adapter

`cris/llm.py` is vendor-neutral at the application boundary. It calls an OpenAI-compatible Chat Completions endpoint using Python's standard `urllib` library. Set the endpoint, API key and model name in `.env`.

The prompt includes the selected release, deterministic risk breakdown, monitoring snapshot, retrieved incident/runbook documents and allowed evidence IDs. It instructs the model not to invent facts and to cite only IDs included in the retrieved evidence. The recommended OpenAI model in `.env.example` is `gpt-6-luna`; the adapter requests JSON output and displays token usage after a live call.

The historical-risk dimension is calculated only from ChromaDB-retrieved incident records. Each candidate gets a blended signal: 60% semantic cosine relevance, 40% structured field overlap, adjusted by a historical-severity multiplier. The best candidate sets the dimension score; scores are not summed across incidents. Similarity is a relevance input, not a failure probability. These weights are prototype assumptions.

The response is parsed as JSON. Citations that are not among retrieved source IDs are removed. This is a validation guard, not a guarantee that every model statement is true; engineers still need to review it.

If credentials or a model name are absent, the workflow uses `build_demo_analysis`. This is deterministic output and is explicitly labelled as demo mode; it is not an LLM result.

## Run the graph

```powershell
.\.venv\Scripts\python.exe -m cris.assess --release REL-2026-041 --demo-mode
```

## Run the UI

```powershell
.\.venv\Scripts\python.exe -m streamlit run cris/app.py
```

## Configure the LLM

Copy `.env.example` to `.env`, add your OpenAI API key to `CRIS_LLM_API_KEY`, and keep `CRIS_LLM_MODEL=gpt-6-luna`. The configured endpoint must expose `POST /chat/completions` and return the standard `choices[0].message.content` response shape. Never commit `.env` or share the API key.

## Important distinction

- ChromaDB finds evidence; it does not write the assessment narrative.
- The risk engine calculates a deterministic prioritization score; the LLM does not control or recalculate it.
- LangGraph orchestrates the steps; it is not itself the LLM.
- Streamlit displays the output; it is not the risk engine.
- No external enterprise connector is live in this prototype.
