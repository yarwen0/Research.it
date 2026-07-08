# Research.it — Backend

FastAPI service that powers the [Research.it](../README.md) research gap discovery
engine: arXiv search, LLM-based extraction, a symbolic gap finder, a citation
graph, trend analysis, and LaTeX literature-review generation — all streamed to the
frontend over Server-Sent Events.

## Requirements

- Python **3.10+**
- An LLM provider (Gemini, OpenRouter, or a local Ollama install)
- Optional: a LaTeX toolchain (`pdflatex`) for `POST /api/latex/compile`

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # configure a provider (see below)
make dev                   # http://127.0.0.1:8000  (docs at /docs)
```

## Configuration

All configuration is via environment variables (loaded from `.env`). See
[`.env.example`](.env.example) for the full list. The provider is chosen with
`LLM_PROVIDER`:

- `gemini` — needs `GEMINI_API_KEY` (default when a key is present)
- `openrouter` — needs `OPENROUTER_API_KEY`
- `ollama` — fully local, no key; requires `ollama serve` plus
  `ollama pull qwen2.5:7b` and `ollama pull nomic-embed-text`

`CORS_ORIGINS` (comma-separated) controls allowed browser origins; it defaults to
`*` for local development.

## Endpoints

| Method | Path                        | Purpose                            |
|--------|-----------------------------|------------------------------------|
| GET    | `/`                         | Health check                       |
| GET    | `/health`                   | Detailed health check              |
| POST   | `/api/research`             | Run the research pipeline (SSE)    |
| POST   | `/api/create_review`        | Generate a literature review (SSE) |
| GET    | `/api/reviews`              | List generated reviews             |
| GET    | `/api/reviews/{review_id}`  | Fetch one review                   |
| POST   | `/api/latex/compile`        | Compile LaTeX to PDF               |
| GET    | `/api/graph/{project_id}/`  | Fetch a project's reference graph  |

## Project structure

```
be-main/
├── main.py              FastAPI app: CORS, routers, health checks, uvicorn entry
├── config.py            Environment loading and LLM provider selection
├── core.py              LLM clients (Gemini/Ollama/OpenRouter) + factory,
│                        PDF extraction, ontology storage, reference graph
├── gap_finder.py        Symbolic research-gap detection (Paper, Gap, GapFinder)
├── api/
│   ├── api.py           Route handlers and SSE streaming pipelines
│   ├── arxiv.py         arXiv search/download/extract + topic generation
│   └── review.py        Literature-review generation (ReviewManager)
├── utils/
│   ├── embeddings.py    Cosine similarity, chunking, relevance ranking, dedup
│   ├── graph.py         Trend/chart data generation (TrendsCreator)
│   └── regex.py         Vendored reference parsing (CERN refextract, GPL-2.0+)
├── constants/
│   ├── prompts/         Extractor / normalizer / review system prompts
│   └── response_formats/ Canonical + extractor JSON schemas
├── examples/            Sample corpus, docs, and runnable example scripts
└── data/                Runtime output — processed papers, graphs (gitignored)
```

## The research pipeline

`POST /api/research` streams the following stages (see
[`api/api.py`](api/api.py)):

1. Generate related topics (unless topics are supplied).
2. Search arXiv per topic, optionally reranking by embedding similarity.
3. For each paper: extract → normalize → map to the ontology.
4. Build the citation + authorship graph.
5. Generate trend analyses and a dataset summary.
6. Run the gap finder and verbalize the top gaps into suggested papers.

## Tests

Pure-logic tests (no network, no API keys):

```bash
pip install -r requirements-dev.txt
make test
```

## Example scripts

The `examples/` directory has standalone scripts that exercise individual stages
against bundled sample data, e.g.:

```bash
# Pure — no provider needed:
python gap_find_example.py                 # gap finder on examples/sample_corpus.json

# Needs a provider key (uses OpenRouter):
python extractor_example.py dreampose      # extract examples/docs/dreampose.txt
```
