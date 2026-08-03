# Research.it — Frontend

![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white) ![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black) ![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white) ![Vitest](https://img.shields.io/badge/tested_with-vitest-6E9F18?logo=vitest&logoColor=white)

Next.js 16 (App Router) web client for the [Research.it](../README.md) research gap
discovery engine. It drives the backend pipeline, renders the streamed results as
interactive charts and a citation graph, and provides a LaTeX editor for the
generated literature reviews.

## Requirements

- Node **20.9+** (22 LTS recommended)
- [pnpm](https://pnpm.io/) (see `packageManager` in `package.json`)
- A running [backend](../be-main/README.md) (default `http://127.0.0.1:8000`)

## Setup

```bash
pnpm install
cp .env.example .env.local     # optional — only to override the backend URL
pnpm dev                        # http://localhost:3000
```

| Script | Purpose |
|---|---|
| `pnpm dev` / `pnpm build` / `pnpm start` | Development, production build, production server |
| `pnpm typecheck` | `tsc --noEmit` |
| `pnpm lint` | ESLint (flat config; Next 16 removed `next lint`) |
| `pnpm test` | Vitest unit tests |
| `pnpm test:e2e` | Playwright end-to-end tests |
| `pnpm generate:api-types` | Regenerate `lib/api-types.ts` from the backend schema |

## Tests

Unit tests ([Vitest](https://vitest.dev/)) cover the pure helpers in `lib/`.
End-to-end tests ([Playwright](https://playwright.dev/)) drive the real UI
with the backend stubbed at the network layer, so neither needs an API
running:

```bash
pnpm test        # units
pnpm test:e2e    # end-to-end
```

## Configuration

| Variable                   | Default                  | Purpose                        |
|----------------------------|--------------------------|--------------------------------|
| `NEXT_PUBLIC_API_URL`      | `http://127.0.0.1:8000`  | Base URL of the backend API.   |
| `NEXT_PUBLIC_SITE_URL`     | (unset)                  | Canonical site URL for Open Graph / Twitter metadata. |

## Tech stack

- **Framework:** Next.js 16 (App Router), React 19, TypeScript
- **Styling:** Tailwind CSS + [shadcn/ui](https://ui.shadcn.com/) primitives
- **Charts:** MUI X Charts, Nivo (heatmap), react-google-charts (sankey), d3-cloud (word cloud)
- **Graphs:** Cytoscape (research graph), Sigma + Graphology (reference graph)
- **Editor:** Monaco (`@monaco-editor/react`) for LaTeX
- **Data flow:** Server-Sent Events consumed by a custom `StreamHandler`
- **Types:** generated from the backend's OpenAPI schema into `lib/api-types.ts`
- **Testing:** Vitest (units), Playwright (e2e, backend stubbed)

## Pages

| Route                   | Description                                     |
|-------------------------|-------------------------------------------------|
| `/`                     | Home — enter a prompt and run the pipeline.     |
| `/editor` `/editor/[id]`| LaTeX editor for generated reviews.             |
| `/graph/[project_id]`   | Interactive citation / authorship graph.        |
| `/r/[id]`               | Shared, read-only view of a review.             |

## Project structure

```
fe-main/
├── app/
│   ├── page.tsx            Home / research entry point
│   ├── layout.tsx          Root layout
│   ├── editor/             LaTeX review editor
│   ├── graph/              Citation graph viewer
│   ├── r/                  Shared review view
│   └── _components/        Feature components (charts, sidebars, results, …)
├── components/ui/          shadcn/ui primitives
├── lib/
│   ├── api.ts              Backend client (research, jobs, graph, LaTeX)
│   ├── api-types.ts        Generated from the backend's OpenAPI schema
│   ├── stream_handler.ts   SSE parsing and dispatch
│   ├── paper-transform.ts  Shape backend payloads for the UI
│   ├── response-store.ts   Research results state
│   └── review-store.ts     Review state
├── e2e/                    Playwright specs
└── hooks/                  React hooks (e.g. use-mobile)
```

## How it connects

`lib/api.ts` posts to `POST /api/research` and streams the SSE response through
`lib/stream_handler.ts`, which dispatches typed status updates (`processing`,
`progress`, `success`, `error`, `completed`) to the UI. Completed runs expose a
`project_id` used to fetch the citation graph via `GET /api/graph/{project_id}/`.

The run itself executes as a background job on the backend, so losing the
connection stops the streaming, not the work. Every event carries a `job_id`
and `sequence`; `resumeResearch()` reconnects at
`/api/jobs/{job_id}/events?after={sequence}` and picks up from there.

Request and response types are generated from the backend's OpenAPI schema, so
a change to a FastAPI model surfaces here as a TypeScript error rather than a
runtime shape mismatch. Regenerate with `pnpm generate:api-types`; CI fails if
the committed types drift.
