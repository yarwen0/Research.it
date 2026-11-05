# Deployment

Four ways to run Research.it, in increasing order of effort.

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

Compose runs Postgres from the `pgvector/pgvector` image: the migrations
enable the `vector` extension for retrieval. Pointing `DATABASE_URL` at another
Postgres needs that extension available and a role allowed to create it.

## 2. Native

See the [root README](README.md#quickstart). You need Python 3.10+, Node 20.9+
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

## 4. Google Cloud (Cloud Run, Cloud SQL, Vertex AI)

Everything is in [`deploy/gcp/`](deploy/gcp): Terraform for the
infrastructure and a Cloud Build pipeline for the images. CI formats and
validates the Terraform against the provider schema on every push; it does
not apply it.

| Resource | What it is for |
|---|---|
| Cloud Run `researchit-api` | The FastAPI service, running as its own service account |
| Cloud Run `researchit-web` | The Next.js frontend |
| Cloud SQL, Postgres 16 | The same schema as compose; the first migration enables pgvector |
| Secret Manager `researchit-database-url` | `DATABASE_URL`, read by the API at startup |
| Cloud Storage bucket, mounted at `/app/data` | Downloaded PDFs and each run's raw output |
| Artifact Registry `researchit` | Images pushed by Cloud Build |
| Service accounts | `researchit-api` (Vertex AI, Cloud SQL, traces, logs), `researchit-web` (nothing), `researchit-deployer` (push images, roll out revisions) |

**No API keys exist anywhere in this deployment.** Vertex AI and Cloud Trace
authorize the API's service account directly. The database password is
generated during `apply` and reaches Cloud SQL and Secret Manager through
write-only arguments, so it is never written to Terraform state.

### First deploy

```bash
cd deploy/gcp/terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id
terraform init
terraform apply                                 # placeholder images at first

cd ../../..
gcloud builds submit --config deploy/gcp/cloudbuild.yaml \
  --service-account "projects/PROJECT_ID/serviceAccounts/$(terraform -chdir=deploy/gcp/terraform output -raw deployer_service_account)" \
  --substitutions _REGION=us-central1
```

The build runs the backend tests, then builds and rolls out the API, reads
its URL, and builds the frontend with that URL compiled in. For continuous
deployment, connect the GitHub repository to Cloud Build and create a trigger
on `main` with the same config and service account.

### Trade-offs this configuration makes

- **One API instance, with CPU always allocated.** Research jobs run inside
  the API process and keep working after the request that started them ends,
  and rate-limit counters are per process. A second instance would split
  both; request-only CPU would stall a job the moment its client disconnects.
- **`api_min_instances` defaults to 0.** The API scales to nothing when idle,
  which is cheap, but an instance can be reclaimed while a job runs with no
  client connected. Set it to 1 to rule that out, at the cost of an always-on
  instance.
- **`db_tier` defaults to `db-f1-micro`**, the cheapest tier that runs
  Postgres 16 with pgvector. It is shared-core and has no SLA.
- **Rate limits key on the address Google's front end saw.** It appends to
  `X-Forwarded-For` instead of replacing it, so the API sets
  `TRUSTED_PROXY_HOPS=1` rather than trusting the left-most entry, which the
  caller controls.
- **Observability is on.** Logs are JSON in Cloud Logging, carrying each
  request's id; spans for every job, stage and LLM call go to Cloud Trace.

### MCP for outside agents

Set `enable_mcp = true` to serve the corpus tools over MCP at the API's
`/mcp/`. Terraform generates the bearer token straight into Secret Manager —
write-only, so it is not in state either — and the `mcp_url` output says
where to point clients:

```bash
gcloud secrets versions access latest --secret researchit-mcp-api-key
```

To tear down, set `deletion_protection = false`, apply, then destroy.

### Vertex AI without deploying

The Vertex provider runs anywhere Application Default Credentials do:

```bash
gcloud auth application-default login
cd be-main
LLM_PROVIDER=vertex GOOGLE_CLOUD_PROJECT=your-project make dev
```

The project needs the Vertex AI API enabled and your account
`roles/aiplatform.user`.

## Environment reference

| Variable                   | Where     | Default                  | Purpose                                    |
|----------------------------|-----------|--------------------------|--------------------------------------------|
| `LLM_PROVIDER`             | backend   | auto-detected            | `gemini` · `openrouter` · `ollama` · `vertex` |
| `GEMINI_API_KEY`           | backend   | —                        | Required unless using Ollama               |
| `OPENROUTER_API_KEY`       | backend   | —                        | Required when `LLM_PROVIDER=openrouter`    |
| `OLLAMA_BASE_URL`          | backend   | `http://localhost:11434` | Local model server                         |
| `GOOGLE_CLOUD_PROJECT`     | backend   | ADC project              | Project for `LLM_PROVIDER=vertex`          |
| `GOOGLE_CLOUD_LOCATION`    | backend   | `us-central1`            | Vertex AI location, or `global`            |
| `VERTEX_MODEL`             | backend   | `gemini-2.5-flash-lite`  | Gemini model on Vertex AI                  |
| `VERTEX_EMBED_MODEL`       | backend   | `text-embedding-005`     | Embedding model on Vertex AI               |
| `TRUSTED_PROXY_HOPS`       | backend   | `0`                      | Proxies that append to `X-Forwarded-For`   |
| `MCP_API_KEY`              | backend   | —                        | Serve MCP at `/mcp/` behind this token     |
| `CORS_ORIGINS`             | backend   | `*`                      | Comma-separated allowed browser origins    |
| `HOST` / `PORT`            | backend   | `0.0.0.0` / `8000`       | Bind address                               |
| `OTEL_TRACES_EXPORTER`     | backend   | `none`                   | `console`, `otlp` or `gcp` (Cloud Trace)   |
| `LLM_PRICES`               | backend   | built-in table           | JSON price overrides for cost estimates    |
| `NEXT_PUBLIC_API_URL`      | frontend  | `http://127.0.0.1:8000`  | Backend URL, inlined at build time         |
| `NEXT_PUBLIC_SITE_URL`     | frontend  | —                        | Canonical URL for Open Graph metadata      |
| `INSTALL_LATEX`            | build arg | `true`                   | Skip TeX Live for a ~700 MB smaller image  |
