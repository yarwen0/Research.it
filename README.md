<div align="center">

<img src="fe-main/public/logo.png" alt="Research.it logo" width="180" />

# Research.it

**A research gap discovery engine.**

[![CI](https://github.com/yarwen0/Research.it/actions/workflows/ci.yml/badge.svg)](https://github.com/yarwen0/Research.it/actions/workflows/ci.yml) ![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white) ![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white) ![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)

</div>

Give it a topic and it searches arXiv, reads the papers, extracts a structured
model of each one (problem → methods → datasets → limitations → future work),
builds a citation graph, surfaces concrete research gaps, and can draft a full
literature review in LaTeX — streaming its progress to a web UI the whole way.

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

## Tech stack

| Layer     | Technologies                                                                       |
|-----------|------------------------------------------------------------------------------------|
| Backend   | Python 3.10+, FastAPI, Uvicorn, Pydantic, arXiv, PyMuPDF, scikit-learn, PyLaTeX     |
| Data      | Postgres / SQLite, SQLAlchemy 2, Alembic                                            |
| Frontend  | Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/ui, MUI X Charts, Cytoscape  |
| AI        | Gemini · OpenRouter · Ollama (local) — chat + embeddings                            |
| Observability | structlog (JSON logs), per-request correlation ids                             |
| Tooling   | pytest, Vitest, Playwright, ruff, mypy, ESLint, GitHub Actions CI                   |
| Infra     | Docker, Docker Compose, Fly.io (API), Vercel (web)                                  |

## Documentation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Request path, design decisions, known limits |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Compose, native and hosted setups |
| [SECURITY.md](SECURITY.md) | Untrusted input surfaces and what constrains them |
| [be-main/evals/README.md](be-main/evals/README.md) | Gap detection benchmark and results |

## Quickstart

### Docker (one command)

```bash
cp .env.example .env      # add a GEMINI_API_KEY — free at aistudio.google.com/apikey
docker compose up --build
```

Frontend on <http://localhost:3000>, API docs on <http://localhost:8000/docs>.

Don't want to sign up for a key? Set `LLM_PROVIDER=ollama` in `.env` and run
`docker compose --profile local-llm up --build` to pull local models instead.

See [DEPLOYMENT.md](DEPLOYMENT.md) for hosted setups (Fly.io + Vercel).

### Native

You need **Python 3.10+**, **Node 20.9+** with **pnpm**, and (optionally) a LaTeX
toolchain (`pdflatex`, e.g. BasicTeX/TeX Live) for PDF review compilation.

#### 1. Backend

```bash
cd be-main
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit — see "LLM providers" below
make dev                       # serves on http://127.0.0.1:8000
```

#### 2. Frontend

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

| Method | Path                          | Purpose                              |
|--------|-------------------------------|--------------------------------------|
| GET    | `/`                           | Health check                         |
| GET    | `/health`                     | Detailed health check                |
| POST   | `/api/research`               | Start a research run (SSE)           |
| GET    | `/api/jobs/{job_id}`          | Status of a research job             |
| GET    | `/api/jobs/{job_id}/events`   | Resume a run's stream (SSE)          |
| POST   | `/api/create_review`          | Generate a literature review (SSE)   |
| GET    | `/api/reviews`                | List generated reviews               |
| GET    | `/api/reviews/{review_id}`    | Fetch one review                     |
| POST   | `/api/latex/compile`          | Compile LaTeX to PDF                 |
| GET    | `/api/graph/{project_id}/`    | Fetch a project's reference graph    |

Interactive API docs are available at `http://127.0.0.1:8000/docs` once the
backend is running.

A run executes as a background job, so losing the connection stops the
streaming, not the work. Every event carries a `job_id` and `sequence`;
reconnect at `/api/jobs/{job_id}/events?after={sequence}` to pick up where it
left off.

The frontend's request and response types are generated from this schema
(`pnpm generate:api-types`), and CI fails if the committed types drift from
the backend.

## Tests

Everything below runs with no network access, no API keys and no LLM.

```bash
cd be-main
pip install -r requirements-dev.txt
make test                       # pytest
ruff check . && mypy            # lint and types
python -m evals.run_eval        # gap detection metrics
```

```bash
cd fe-main
pnpm test                       # Vitest unit tests
pnpm typecheck                  # tsc
pnpm test:e2e                   # Playwright, backend stubbed at the network layer
```

CI runs all of it, plus migrations against real Postgres and both Docker
image builds.

## Does the gap finder actually work?

Measured, not asserted. [`be-main/evals/`](be-main/evals/README.md) holds an
18-paper benchmark with hand-labelled ground truth:

```bash
cd be-main && python -m evals.run_eval
```

On the shipped configuration: **precision 0.722, recall 0.188, F1 0.299.**

The detector is precise and misses a lot — it returns 18 of 69 genuine gaps,
because the API caps output at 5 per gap type. Raising that cap to 40 gives
F1 0.548 at precision 0.489. Neither is obviously wrong for a UI showing a
short list of suggestions, but it was not a trade-off anyone had made
deliberately before it could be measured.

Building the harness immediately surfaced a real defect: gap detection was
**non-deterministic**, returning F1 between 0.425 and 0.520 on identical
input, because tied scores were broken by `set` iteration order and Python
randomises string hashing per process. Fixed, and pinned by a test that runs
the finder under several `PYTHONHASHSEED` values.

[Full methodology, per-type numbers, and an error analysis.](be-main/evals/README.md)

## License

[MIT](LICENSE).

`be-main/utils/regex.py` is vendored from CERN's
[refextract](https://github.com/inspirehep/refextract) and remains under its
original GPL-2.0-or-later license (see the header in that file).
