variable "project_id" {
  description = "Google Cloud project to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL, Artifact Registry and the data bucket."
  type        = string
  default     = "us-central1"
}

variable "api_image" {
  description = <<-EOT
    Image for the API on first apply. Cloud Build rolls out every image after
    that, and Terraform ignores the difference, so this only needs to exist.
  EOT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "web_image" {
  description = "Image for the web frontend on first apply; see api_image."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "vertex_location" {
  description = "Vertex AI location for Gemini and embeddings, or \"global\"."
  type        = string
  default     = "us-central1"
}

variable "vertex_model" {
  description = "Gemini model the API calls through Vertex AI."
  type        = string
  default     = "gemini-2.5-flash-lite"
}

variable "db_tier" {
  description = <<-EOT
    Cloud SQL machine tier. The shared-core default is the cheapest that runs
    Postgres 16 with pgvector; it carries no SLA. db-custom-1-3840 is the
    smallest dedicated tier.
  EOT
  type        = string
  default     = "db-f1-micro"
}

variable "db_password_version" {
  description = <<-EOT
    Bump to rotate the database password. It is generated afresh on every run
    but only sent to Cloud SQL and Secret Manager when this changes.
  EOT
  type        = number
  default     = 1
}

variable "api_min_instances" {
  description = <<-EOT
    Research jobs run inside the API process and outlive the request that
    starts them. At 0 the service can scale to nothing when idle, which is
    cheap but means a job left running with no client connected can be cut
    short when its instance is reclaimed. 1 keeps an instance up at all times.
  EOT
  type        = number
  default     = 0
}

variable "public" {
  description = "Serve both services to unauthenticated callers."
  type        = bool
  default     = true
}

variable "extra_cors_origins" {
  description = "Browser origins allowed to call the API besides the web service, e.g. a custom domain."
  type        = list(string)
  default     = []
}

variable "deletion_protection" {
  description = "Refuse to destroy the database and services. Turn off only to tear down."
  type        = bool
  default     = true
}
