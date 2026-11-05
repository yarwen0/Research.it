# Roadmap: from research tool to agentic platform

Research.it already finds papers, extracts a structured record from each one,
builds a citation graph and surfaces research gaps. What it cannot do yet is
answer questions about the corpus it built, explain what a run cost, or run
anywhere other than a laptop, Fly.io and Vercel.

This document plans the work that closes those gaps. Each phase ships on its
own, with tests and docs, and is marked off below as it lands.

## Principles

Carried over from the rest of the codebase, and binding on every phase:

- **Measured, not asserted.** A retrieval or agent feature ships with a
  benchmark that produces a number, the same way the gap finder does in
  [`be-main/evals/`](be-main/evals/README.md).
- **Provider-agnostic.** Everything works on Gemini, OpenRouter, local Ollama
  and (from phase 6) Vertex AI. Nothing depends on one vendor's tool-calling
  dialect.
- **Offline in CI.** No test needs a network, an API key or a model. LLMs and
  embedders are replaced with deterministic fakes; real-model results are
  recorded in the docs with the command that reproduces them.
- **Honest limits.** Every phase adds its trade-offs to the known-limits list
  in [ARCHITECTURE.md](ARCHITECTURE.md).

## Capability map

| Area | Today | After this roadmap |
|---|---|---|
| LLM observability | structlog, request ids | Tokens, latency, tokens/sec and estimated cost for every LLM call; per-run rollups by stage and model; OpenTelemetry spans following the GenAI semantic conventions |
| Retrieval | Embedding rerank of arXiv abstracts; throwaway chunk ranking inside reviews | Persistent vector store (pgvector on Postgres, portable fallback on SQLite) holding unstructured full text and structured extraction records; hybrid BM25 + dense retrieval fused with RRF |
| Question answering | — | Retrieval-augmented answers with validated citations, and an explicit refusal when the corpus does not contain the answer |
| Agents | — | Multi-agent research assistant on LangGraph: a supervisor delegating to specialists, ReAct tool use, a critic that sends ungrounded drafts back for revision, and conversations persisted per thread |
| Interoperability | REST + SSE | MCP server (stdio and streamable HTTP) exposing corpus search, grounded Q&A, gap analysis and the citation graph to any MCP client |
| Evaluation | Gap-finder benchmark | Retrieval benchmark (recall@k, MRR), citation validity checks, a prompt-injection detector with its own labelled set, all gated in CI |
| Cloud | Fly.io + Vercel | Google Cloud: Vertex AI provider (ADC, no keys), Cloud Run, Cloud SQL Postgres with pgvector, Secret Manager, Cloud Storage volume, Terraform, Cloud Build, Cloud Trace |
| Security | Rate limits, no auth | API keys on write and MCP endpoints; untrusted PDF text screened and fenced before it reaches a prompt |

## Phases

### Phase 1 — LLM telemetry

**Why.** A run makes dozens to hundreds of LLM calls and nothing records what
they cost, which stage is slow, or what throughput the local model actually
delivers. The reference-extraction cap in `api/arxiv.py` was tuned from timings
collected by hand, one run at a time, and copied into a comment.

**Design.**

- One choke point: every provider client records each call through
  `telemetry.track_llm_call()`, so no call escapes accounting regardless of
  which module made it.
- Usage comes from the provider when it reports it — Gemini `usageMetadata`,
  Ollama `prompt_eval_count` / `eval_count` / `eval_duration`, OpenRouter
  `usage` — and is estimated (and flagged as estimated) when it does not.
- Tokens/sec uses the model's own decode time where available (Ollama) and
  end-to-end latency otherwise; the two are labelled differently because they
  are different numbers.
- Cost comes from a dated price table, overridable by env. Local inference is
  priced at zero; unknown models report no cost rather than a guess.
- Calls are attributed to the active job and pipeline stage through context
  variables. Blocking work moves from `run_in_executor` to `asyncio.to_thread`,
  which carries that context into worker threads — and with it the
  OpenTelemetry parent span.
- Spans: job → stage → LLM call, with `gen_ai.*` attributes. Export is off by
  default; `OTEL_TRACES_EXPORTER=console|otlp|gcp` turns it on.

**Deliverables.** `telemetry/` package, `llm_calls` table and migration,
`GET /api/jobs/{job_id}/metrics` (totals, by stage, by model, p50/p95 latency),
tests.

**Done when.** A stubbed research run produces per-stage token, latency and
cost rollups through the API, with no network access.

### Phase 2 — Vector store and indexing

**Why.** Every paper's full text is read once for extraction and then thrown
away. The review pipeline re-downloads and re-embeds papers on every request.
There is nothing durable to retrieve from.

**Design.**

- A `chunks` table holding both kinds of data the pipeline produces:
  *unstructured* full-text chunks (section-aware, bibliography excluded) and
  one *structured* profile chunk per paper rendered from its extraction
  (problem, methods, datasets, limitations, future work).
- Embeddings live in the same database as the papers they belong to:
  **pgvector** on Postgres, float32 blobs searched with numpy on SQLite. One
  datastore means cascade deletes and transactional consistency with the rest
  of the graph, and Cloud SQL supports the extension.
- Search is always scoped to one project, so it is an exact scan behind the
  `project_id` index rather than an ANN index — at a few thousand chunks per
  project exact search is fast, and an HNSW index would post-filter by project
  and lose recall.
- Asymmetric embeddings: document and query texts are embedded with the task
  hint each provider supports (Gemini `taskType`, nomic `search_document:` /
  `search_query:` prefixes).
- Indexing is a pipeline stage after the graph is saved. A failure there is
  reported and contained; it does not fail the run.

**Deliverables.** `retrieval/` package (chunker, store, indexer), migration
with the pgvector extension, compose and CI moved to the `pgvector/pgvector`
image, a backfill command for projects indexed before this phase.

**Done when.** A stubbed run leaves searchable chunks behind on both SQLite
and Postgres, and CI proves the migration on Postgres.

### Phase 3 — Hybrid retrieval and grounded answers

**Why.** Dense embeddings blur exactly the tokens that matter in this domain —
dataset names, metric acronyms, model identifiers like `Human3.6M` or
`MPJPE`. Lexical search handles those and misses paraphrase. Neither alone is
the right default, and which mix is best is an empirical question.

**Design.**

- BM25 over the project's chunks and dense vector search, fused with
  Reciprocal Rank Fusion, with a per-paper cap so one long paper cannot
  monopolise the context.
- `POST /api/projects/{project_id}/ask`: retrieve, answer from numbered
  sources only, validate every citation against the sources actually supplied,
  and refuse without calling the LLM when retrieval finds nothing relevant.
- Retrieved text is untrusted. It is fenced as data, never concatenated into
  instructions.

**Deliverables.** `services/rag.py`, the endpoint, and a retrieval benchmark
under `evals/` comparing dense, BM25 and hybrid on labelled questions.
Embeddings for the benchmark are precomputed and committed, so CI scores real
embeddings offline.

**Done when.** The benchmark reports recall@k and MRR for all three
strategies, and the shipped default is whichever one the numbers support.

### Phase 4 — Multi-agent research assistant

**Why.** Real questions cross the system's boundaries: "which gaps in this
corpus involve datasets nobody has cited?" needs the gap finder, the citation
graph and the text together. A single prompt cannot route between them.

**Design** — a LangGraph state graph:

```
supervisor ──┬─> literature specialist (ReAct over corpus search) ──┐
             ├─> gap analyst (symbolic gap finder)                  ├─> writer ─> critic ─┬─> answer
             └─> citation analyst (graph queries)                   ┘     ^               │
                                                                          └── revise ─────┘
```

- **Hierarchical delegation**: the supervisor decomposes the question and fans
  out only to the specialists it needs, in parallel.
- **ReAct**: specialists alternate reasoning and tool calls. Actions are
  emitted as schema-constrained JSON rather than through native tool-calling
  APIs, which differ per provider and are unreliable on 7B local models;
  constrained decoding works on all four providers.
- **Self-reflection**: a critic checks the draft against the collected
  evidence and returns it for revision, with a hard cap on rounds.
- **State**: conversations persist per thread in the database, and history is
  windowed to a token budget rather than replayed whole.
- Every node streams over SSE, so the UI shows the plan, the tool calls and
  the critique as they happen.

**Done when.** Scripted-LLM tests cover routing, tool execution, the bounded
revision loop and thread persistence.

### Phase 5 — MCP server

**Why.** The corpus, the gap finder and the citation graph are useful to more
than this UI. MCP makes them tools any agent can call — Claude, Gemini via
Google's Agent Development Kit, or an IDE assistant — without a bespoke
integration for each.

**Design.** One server definition, two transports: stdio for desktop clients,
and streamable HTTP mounted on the API behind an API key. Tools: list
projects, search a corpus, ask a grounded question, find gaps, get a paper's
structured record, summarise the citation graph.

**Done when.** An in-memory MCP client lists and calls every tool in tests.

### Phase 6 — Google Cloud deployment

**Design.**

- **Vertex AI provider**: Gemini via Vertex with Application Default
  Credentials, so production holds no API keys; `text-embedding-005` for
  embeddings, which reports token counts that feed phase 1's telemetry.
- **Terraform** for Cloud Run (API and web), Cloud SQL Postgres with pgvector,
  Secret Manager, Artifact Registry, a Cloud Storage bucket mounted at
  `/app/data`, and a least-privilege service account.
- **Cloud Build** pipeline: test, build, push, deploy.
- **Cloud Trace** via the OTLP endpoint, reusing phase 1's spans unchanged.
- The in-process job runner needs CPU between requests, so the API runs with
  CPU always allocated and a single instance. The config says so, and why.

### Phase 7 — Safety and evaluation gates

- A prompt-injection screen for untrusted PDF text, with a labelled set that
  includes the hard case: papers *about* prompt injection, which quote attacks
  verbatim and must not be dropped from their own corpus.
- Citation validity and refusal correctness for grounded answers.
- CI gates on the retrieval benchmark, alongside the existing gap-finder gate.

### Phase 8 — Frontend surfaces

An "ask this corpus" panel that streams the assistant's steps and renders
citations as links to the source paper, and a run-telemetry card showing cost,
tokens, latency and throughput by stage.

### Phase 9 — Authentication perimeter

API keys, stored hashed, required on write endpoints and the MCP endpoint when
`AUTH_REQUIRED` is set; rate limits keyed by API key instead of by IP.

## Status

| Phase | Status |
|---|---|
| 1. LLM telemetry | Done |
| 2. Vector store and indexing | Done |
| 3. Hybrid retrieval and grounded answers | Planned |
| 4. Multi-agent research assistant | Planned |
| 5. MCP server | Planned |
| 6. Google Cloud deployment | Planned |
| 7. Safety and evaluation gates | Planned |
| 8. Frontend surfaces | Planned |
| 9. Authentication perimeter | Planned |

## Non-goals

- **Replacing the symbolic gap finder with an LLM.** Its value is that it is
  inspectable and measurable; the agent calls it as a tool.
- **A separate vector database service.** pgvector keeps embeddings
  transactional with the papers they describe, and per-project corpora are far
  below the scale where a dedicated service pays for its operational cost.
- **A distributed job queue.** The seam exists (`services/jobs.py`); it is
  not needed until there is more than one worker.
