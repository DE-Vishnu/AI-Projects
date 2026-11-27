# Day 2 learning guide — from raw operational data to semantic evidence

## The goal

By the end of Day 2, a release description should be able to retrieve relevant historical incidents and the exact sections of runbooks that explain what engineers should check. This is the retrieval half of Retrieval-Augmented Generation (RAG). We are not generating an LLM answer yet.

## 1. Ingestion and normalization

An enterprise may store incidents in Jira, ServiceNow, CSV exports or a local file. Their field names and payload shapes differ. The scoring and retrieval parts of CRIS should not need to know which system supplied the data.

The ingestion adapter converts source-specific records into one canonical `Incident` model:

```text
Jira API ──────┐
CSV export ────┼──> source adapter ──> Incident model ──> CRIS logic
JSON file ────┘
```

This separation is called **normalization**. The same canonical object is used regardless of source. Our CSV list-valued fields are JSON-encoded inside each cell so commas inside values do not break parsing.

## 2. Why runbooks are Markdown

Runbooks are documents, not just rows. Markdown is lightweight, readable in Git and supports headings, lists and code blocks. The prototype uses YAML front matter for metadata such as `runbook_id`, `service` and `triggers`, while the body contains the human-readable procedure.

Metadata is kept separately from the document body so that Chroma can filter and cite sources without losing the readable instructions.

## 3. Why chunk documents?

A 20-page runbook is too broad to retrieve as one giant text record. If the engineer asks about a watermark change, the relevant material may be in the checks and rollback sections, not in the whole document.

Chunking divides a document into smaller, meaningful sections. CRIS first splits by Markdown headings, then groups paragraphs up to a character limit. A small overlap helps keep context when a section crosses a chunk boundary.

For a chunk, we preserve metadata such as:

- `runbook_id`: parent document identity
- `service`: service this procedure applies to
- `section`: heading that produced the chunk
- `chunk_index`: position within the runbook
- `source_file`: original Markdown file

The current character-based splitter is intentionally simple. Production chunking should use token counts, respect code/table boundaries and be tested against the actual embedding model's context window.

## 4. What is an embedding?

An embedding model converts text into a list of numbers (a vector). Texts with related meaning tend to have vectors that are close under a vector-distance measure.

Example:

```text
"The pipeline skipped late-arriving records"
"Incremental watermark advanced before delayed events were committed"
```

These sentences do not share many exact words, but they describe a related failure pattern. Semantic embeddings can help retrieve the second description when the release mentions the first concept.

CRIS uses Chroma's default local embedding function, `all-MiniLM-L6-v2`, backed by ONNX Runtime. Chroma can automatically embed documents during `upsert` and embed query text during `query`. The first run may download model files; after that, model inference runs locally.

## 5. What is ChromaDB doing?

Think of Chroma as a vector index with document storage and metadata:

| Field | Example |
|---|---|
| ID | `incident::INC-1042` |
| Document | Text describing the root cause, impact and resolution |
| Embedding | Vector generated from that text |
| Metadata | `doc_type=incident`, `service=orders_ingestion`, `incident_id=INC-1042` |

The Python code uses `PersistentClient`, so the vector index is stored on disk under `storage/chroma`. A collection is a logical group of records. We use one collection, `cris_knowledge`, and filter it by `doc_type` to retrieve incidents and runbooks separately.

## 6. How semantic retrieval works

For release REL-2026-041, CRIS constructs one query text containing the release name, service, description, change types, components and dependencies.

It then performs two searches:

1. Search records where `doc_type=incident`.
2. Search records where `doc_type=runbook`.

Chroma returns the nearest documents and their cosine distances. In a cosine-distance collection, lower distance means closer vectors. The prototype displays `1 - distance` as a cosine similarity score. This is only a ranking signal; it is not a failure probability or a calibrated confidence percentage.

## 7. RAG: what have we built and what remains?

RAG means **Retrieval-Augmented Generation**:

```text
User/release query
       |
       v
Retriever ----> relevant incident/runbook chunks
       |                         |
       +-------------------------+
                    |
                    v
          Context sent to an LLM
                    |
                    v
       Grounded explanation + actions
```

Day 2 builds the data ingestion, embeddings, vector store and retriever. Day 3 will add the LLM generation step and require it to cite the retrieved incident/runbook IDs. Retrieval is not the same as generation: Chroma finds evidence; the LLM will later explain that evidence.

## 8. Why monitoring snapshots are separate

Release details describe a proposed code/configuration change. Monitoring snapshots describe the changing runtime state of a service. They have different lifecycles and timestamps, so they should be separate entities.

The `MonitoringSource` protocol is an interface. The JSON adapter implements it today. A future New Relic/Datadog/Prometheus adapter can implement the same method without requiring the scoring logic to know the monitoring vendor.

The sample connector returns the latest snapshot for a requested service. A production design must also handle stale snapshots, time windows, metric units, missing telemetry, baseline comparisons and API rate limits.

## 9. What to inspect in the code

Read these files in this order:

1. `cris/ingestion/incidents.py` — compare JSON and CSV normalization.
2. `cris/ingestion/runbooks.py` — see front matter parsing and chunk creation.
3. `cris/retrieval/indexer.py` — see how source records become Chroma documents.
4. `cris/retrieval/chroma_store.py` — study persistent collections, upsert and query.
5. `cris/retrieval/release_search.py` — see how release context becomes the semantic query.
6. `cris/ingestion/monitoring.py` — understand the vendor-neutral monitoring interface.
7. `cris/day2.py` — see how the commands connect the components.

## 10. Questions you should be able to answer

- Why do we normalize different source systems into one Incident model?
- Why keep both a document ID and source metadata in Chroma?
- Why chunk runbooks but keep each short incident as one document?
- What is an embedding, and who creates it in this implementation?
- What does Chroma persist to disk?
- What does cosine distance mean, and why is it not a probability?
- Why retrieve incidents and runbooks separately?
- Why is monitoring health stored separately from the release record?
- What is the difference between the RAG retrieval step and the LLM generation step?
