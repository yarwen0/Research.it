# Research.it

**A research gap discovery engine.** Give it a topic and it searches arXiv, reads
the papers, extracts a structured model of each one (problem → methods → datasets →
limitations → future work), builds a citation graph, surfaces concrete research
gaps, and can draft a full literature review in LaTeX — streaming its progress to a
web UI the whole way.

> Built at Hatchathon 2025.

---

## What it does

Given a research prompt (e.g. *"diffusion models for pose transfer"*) the pipeline:

1. **Expands topics** — an LLM generates related sub-topics to widen the search.
2. **Searches arXiv** — fetches candidate papers per topic, with optional
   vector-based reranking to keep only the most relevant.
3. **Extracts & normalizes** — downloads each PDF, pulls the text, and runs an
   extraction → normalization → ontology-mapping pipeline to produce a canonical
   record per paper (problem, methods, datasets, limitations, future work).
4. **Builds a graph** — assembles a citation + authorship reference graph.
5. **Finds gaps** — a symbolic [`GapFinder`](be-main/gap_finder.py) detects
   method-transfer, dataset-transfer, limitation-pressure, and unmet future-work
   gaps, then uses the LLM purely to *verbalize* them into suggested papers.
6. **Analyzes trends** — produces chart-ready trend and dataset summaries.
7. **Writes reviews** — on request, generates a cited literature review in LaTeX
   and compiles it to PDF.

Progress is streamed to the frontend over Server-Sent Events (SSE).

## Repository layout

```
researchit/
├── be-main/   FastAPI backend — arXiv, LLM pipeline, gap finder, graph, reviews
└── fe-main/   Next.js frontend — research UI, charts, citation graph, LaTeX editor
```

Each subproject has its own README with details:

- [`be-main/README.md`](be-main/README.md) — backend architecture, endpoints, config
- [`fe-main/README.md`](fe-main/README.md) — frontend stack, pages, environment

## Quickstart

You need **Python 3.10+**, **Node 18+** with **pnpm**, and (optionally) a LaTeX
toolchain (`pdflatex`, e.g. BasicTeX/TeX Live) for PDF review compilation.

### 1. Backend

```bash
cd be-main
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit — see "LLM providers" below
make dev                       # serves on http://127.0.0.1:8000
```

### 2. Frontend

```bash
cd fe-main
pnpm install
cp .env.example .env.local     # optional: point at a non-default backend
pnpm dev                       # serves on http://localhost:3000
```

The frontend talks to the backend at `NEXT_PUBLIC_API_URL` (default
`http://127.0.0.1:8000`).

## LLM providers

The backend runs against one of three providers, selected with `LLM_PROVIDER`:

| Provider     | Key needed        | Notes                                            |
|--------------|-------------------|--------------------------------------------------|
| `gemini`     | `GEMINI_API_KEY`  | Default when a Gemini key is present.             |
| `openrouter` | `OPENROUTER_API_KEY` | Access to many hosted models.                  |
| `ollama`     | none              | Fully local, no rate limits. Requires Ollama.     |

For local, no-API-key runs:

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
# then set LLM_PROVIDER=ollama in be-main/.env
```

See [`be-main/.env.example`](be-main/.env.example) for every option.

## API endpoints

| Method | Path                        | Purpose                              |
|--------|-----------------------------|--------------------------------------|
| GET    | `/`                         | Health check                         |
| GET    | `/health`                   | Detailed health check                |
| POST   | `/api/research`             | Run the research pipeline (SSE)      |
| POST   | `/api/create_review`        | Generate a literature review (SSE)   |
| GET    | `/api/reviews`              | List generated reviews               |
| GET    | `/api/reviews/{review_id}`  | Fetch one review                     |
| POST   | `/api/latex/compile`        | Compile LaTeX to PDF                  |
| GET    | `/api/graph/{project_id}/`  | Fetch a project's reference graph    |

Interactive API docs are available at `http://127.0.0.1:8000/docs` once the
backend is running.

## Tests

Backend logic has a pytest suite (no network or API keys required):

```bash
cd be-main
pip install -r requirements-dev.txt
make test
```

## License

`be-main/utils/regex.py` is vendored from CERN's
[refextract](https://github.com/inspirehep/refextract) and remains under its
original GPL-2.0-or-later license (see the header in that file). No repository-wide
license has been set for the rest of the project yet.
