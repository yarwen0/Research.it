# Deployment

Three ways to run Research.it, in increasing order of effort.

## 1. Docker Compose (recommended for trying it out)

```bash
cp .env.example .env      # add a GEMINI_API_KEY
docker compose up --build
```

- Frontend — <http://localhost:3000>
- Backend docs — <http://localhost:8000/docs>

No API key? Run entirely on local models instead:

```bash
# set LLM_PROVIDER=ollama in .env first
docker compose --profile local-llm up --build
```

The `ollama-pull` service fetches `qwen2.5:7b` and `nomic-embed-text` on first
start (~5 GB), then exits. Subsequent runs reuse the `ollama-models` volume.

## 2. Native

See the [root README](README.md#quickstart). You need Python 3.10+, Node 18+
with pnpm, and optionally a LaTeX toolchain.

## 3. Hosted (Fly.io + Vercel)

The split is deliberate: the backend is a long-lived streaming service with
disk state, the frontend is static-ish and benefits from a CDN.

### Backend → Fly.io

[`be-main/fly.toml`](be-main/fly.toml) is checked in and ready.

```bash
cd be-main
fly launch --no-deploy --copy-config
fly volumes create researchit_data --size 3
fly secrets set \
  GEMINI_API_KEY=your_key \
  CORS_ORIGINS=https://your-frontend.vercel.app
fly deploy
```

Notes:

- **The volume is not optional.** Generated papers, graphs and reviews are
  written under `/app/data`; without a mount they vanish on each deploy.
- 2 GB of memory is the practical floor — the pipeline holds PDF text and
  embedding matrices in memory.
- `auto_stop_machines = "suspend"` keeps cold starts fast while still scaling
  to zero. Concurrency limits are low on purpose: one research run is minutes
  of CPU and network, not milliseconds.

### Frontend → Vercel

```bash
cd fe-main
vercel --prod
```

Set the project root to `fe-main` and add these environment variables:

| Variable               | Value                                  |
|------------------------|----------------------------------------|
| `NEXT_PUBLIC_API_URL`  | `https://researchit-api.fly.dev`       |
| `NEXT_PUBLIC_SITE_URL` | `https://your-frontend.vercel.app`     |

`NEXT_PUBLIC_*` variables are inlined at build time, so changing either one
requires a redeploy, not just a restart.

### After deploying

Point `CORS_ORIGINS` on the backend at the real frontend origin. Leaving it at
the `*` default means any site can call your API.

## Environment reference

| Variable                   | Where     | Default                  | Purpose                                    |
|----------------------------|-----------|--------------------------|--------------------------------------------|
| `LLM_PROVIDER`             | backend   | auto-detected            | `gemini` · `openrouter` · `ollama`         |
| `GEMINI_API_KEY`           | backend   | —                        | Required unless using Ollama               |
| `OPENROUTER_API_KEY`       | backend   | —                        | Required when `LLM_PROVIDER=openrouter`    |
| `OLLAMA_BASE_URL`          | backend   | `http://localhost:11434` | Local model server                         |
| `CORS_ORIGINS`             | backend   | `*`                      | Comma-separated allowed browser origins    |
| `HOST` / `PORT`            | backend   | `0.0.0.0` / `8000`       | Bind address                               |
| `NEXT_PUBLIC_API_URL`      | frontend  | `http://127.0.0.1:8000`  | Backend URL, inlined at build time         |
| `NEXT_PUBLIC_SITE_URL`     | frontend  | —                        | Canonical URL for Open Graph metadata      |
| `INSTALL_LATEX`            | build arg | `true`                   | Skip TeX Live for a ~700 MB smaller image  |
