# Google Cloud deployment

- [`terraform/`](terraform) — Cloud Run (API and web), Cloud SQL Postgres 16
  with pgvector, Secret Manager, Artifact Registry, a Cloud Storage volume
  and least-privilege service accounts.
- [`cloudbuild.yaml`](cloudbuild.yaml) — tests, builds and rolls out both
  images.

How to deploy, and the trade-offs the configuration makes, are in
[DEPLOYMENT.md](../../DEPLOYMENT.md#4-google-cloud-cloud-run-cloud-sql-vertex-ai).
