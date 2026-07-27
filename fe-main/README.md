# Research.it — Frontend

![Next.js](https://img.shields.io/badge/Next.js-14-000000?logo=nextdotjs&logoColor=white) ![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black) ![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white) ![Vitest](https://img.shields.io/badge/tested_with-vitest-6E9F18?logo=vitest&logoColor=white)

Next.js 14 (App Router) web client for the [Research.it](../README.md) research gap
discovery engine. It drives the backend pipeline, renders the streamed results as
interactive charts and a citation graph, and provides a LaTeX editor for the
generated literature reviews.

## Requirements

- Node **18+**
- [pnpm](https://pnpm.io/) (see `packageManager` in `package.json`)
- A running [backend](../be-main/README.md) (default `http://127.0.0.1:8000`)

## Setup

```bash
pnpm install
cp .env.example .env.local     # optional — only to override the backend URL
pnpm dev                        # http://localhost:3000
```

Other scripts: `pnpm build`, `pnpm start`, `pnpm lint`, `pnpm test`.

## Tests

Unit tests (via [Vitest](https://vitest.dev/)) cover the pure helpers in `lib/`:

```bash
pnpm test
```

## Configuration

| Variable                   | Default                  | Purpose                        |
|----------------------------|--------------------------|--------------------------------|
| `NEXT_PUBLIC_API_URL`      | `http://127.0.0.1:8000`  | Base URL of the backend API.   |
| `NEXT_PUBLIC_SITE_URL`     | (unset)                  | Canonical site URL for Open Graph / Twitter metadata. |

## Tech stack

- **Framework:** Next.js 14 (App Router), React 18, TypeScript
- **Styling:** Tailwind CSS + [shadcn/ui](https://ui.shadcn.com/) primitives
- **Charts:** MUI X Charts, Nivo, ag-charts, react-google-charts, d3-cloud
- **Graphs:** Cytoscape, Sigma, Graphology, React Flow (`@xyflow/react`)
- **Editor:** Monaco (`@monaco-editor/react`) for LaTeX
- **Data flow:** Server-Sent Events consumed by a custom `StreamHandler`

## Pages

| Route                   | Description                                     |
|-------------------------|-------------------------------------------------|
| `/`                     | Home — enter a prompt and run the pipeline.     |
| `/editor` `/editor/[id]`| LaTeX editor for generated reviews.             |
| `/graph/[project_id]`   | Interactive citation / authorship graph.        |
| `/r/[id]`               | Shared, read-only view of a review.             |
| `/pricing`              | Pricing page.                                   |

## Project structure

```
fe-main/
├── app/
│   ├── page.tsx            Home / research entry point
│   ├── layout.tsx          Root layout
│   ├── editor/             LaTeX review editor
│   ├── graph/              Citation graph viewer
│   ├── r/                  Shared review view
│   ├── pricing/            Pricing page
│   └── _components/        Feature components (charts, sidebars, results, …)
├── components/ui/          shadcn/ui primitives
├── lib/
│   ├── api.ts              Backend client (research, graph, LaTeX compile)
│   ├── stream_handler.ts   SSE parsing and dispatch
│   ├── paper-transform.ts  Shape backend payloads for the UI
│   ├── response-store.ts   Research results state
│   └── review-store.ts     Review state
└── hooks/                  React hooks (e.g. use-mobile)
```

## How it connects

`lib/api.ts` posts to `POST /api/research` (and `/api/create_review`) and streams
the SSE response through `lib/stream_handler.ts`, which dispatches typed status
updates (`processing`, `progress`, `success`, `error`, `completed`) to the UI.
Completed runs expose a `project_id` used to fetch the citation graph via
`GET /api/graph/{project_id}/`.
