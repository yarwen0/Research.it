locals {
  services = [
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtrace.googleapis.com",
    "iam.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
    "telemetry.googleapis.com",
  ]

  api_env = {
    LLM_PROVIDER          = "vertex"
    GOOGLE_CLOUD_PROJECT  = var.project_id
    GOOGLE_CLOUD_LOCATION = var.vertex_location
    VERTEX_MODEL          = var.vertex_model
    OTEL_TRACES_EXPORTER  = "gcp"
    OTEL_SERVICE_NAME     = "researchit-api"
    LOG_JSON              = "1"
    # Every URL Cloud Run serves the frontend on. The web service does not
    # depend on the API here — its build bakes the API URL in (see
    # cloudbuild.yaml) — so this creates no cycle.
    CORS_ORIGINS = join(",", concat(google_cloud_run_v2_service.web.urls, var.extra_cors_origins))
    # Google's front end appends the caller's address to X-Forwarded-For
    # rather than replacing the header, so the rate limiter counts one hop
    # from the right. See be-main/rate_limit.py.
    TRUSTED_PROXY_HOPS = "1"
  }
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  service            = each.value
  disable_on_destroy = false
}

# --- Images -----------------------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  repository_id = "researchit"
  location      = var.region
  format        = "DOCKER"
  description   = "Research.it API and web images, pushed by Cloud Build."

  depends_on = [google_project_service.enabled]
}

# --- Identities ---------------------------------------------------------------

resource "google_service_account" "api" {
  account_id   = "researchit-api"
  display_name = "Research.it API on Cloud Run"
}

resource "google_service_account" "web" {
  account_id   = "researchit-web"
  display_name = "Research.it web frontend on Cloud Run"
}

resource "google_service_account" "deployer" {
  account_id   = "researchit-deployer"
  display_name = "Research.it deploys from Cloud Build"
}

# Everything the API does, and nothing else. It holds no API keys: Vertex AI
# and Cloud Trace authorize this identity directly.
resource "google_project_iam_member" "api" {
  for_each = toset([
    "roles/aiplatform.user",        # Gemini and embeddings on Vertex AI
    "roles/cloudsql.client",        # the Cloud SQL socket
    "roles/telemetry.tracesWriter", # spans to Cloud Trace over OTLP
    "roles/logging.logWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "deployer" {
  for_each = toset([
    "roles/run.developer",           # roll out new revisions
    "roles/artifactregistry.writer", # push images
    "roles/logging.logWriter",       # build logs
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Rolling out a revision that runs as a service account means acting as it.
resource "google_service_account_iam_member" "deployer_acts_as" {
  for_each = {
    api = google_service_account.api.name
    web = google_service_account.web.name
  }

  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# --- Database -------------------------------------------------------------------

resource "google_sql_database_instance" "main" {
  name                = "researchit"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_autoresize   = true

    backup_configuration {
      enabled = true
    }

    # Reachable only through the Cloud SQL connector, which authenticates
    # with IAM. No network is allowlisted.
    ip_configuration {
      ipv4_enabled = true
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_sql_database" "app" {
  name     = "researchit"
  instance = google_sql_database_instance.main.name
}

# Opened afresh on every run and never stored: it reaches Cloud SQL and Secret
# Manager only through write-only arguments, sent when db_password_version
# changes. Letters and digits only, since it lands inside a URL.
ephemeral "random_password" "db" {
  length  = 32
  special = false
}

# Users created this way belong to cloudsqlsuperuser, which is what lets the
# app's first migration run CREATE EXTENSION vector.
resource "google_sql_user" "app" {
  name                = "researchit"
  instance            = google_sql_database_instance.main.name
  password_wo         = ephemeral.random_password.db.result
  password_wo_version = var.db_password_version
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "researchit-database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  # psycopg connects through the unix socket Cloud Run mounts at /cloudsql.
  secret_data_wo = join("", [
    "postgresql+psycopg://${google_sql_user.app.name}:${ephemeral.random_password.db.result}",
    "@/${google_sql_database.app.name}",
    "?host=/cloudsql/${google_sql_database_instance.main.connection_name}",
  ])
  secret_data_wo_version = var.db_password_version
}

resource "google_secret_manager_secret_iam_member" "api_reads_database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

# --- Files ----------------------------------------------------------------------

# Downloaded PDFs and each run's raw extraction output, which the review
# pipeline reads back. Cloud Run's own disk is memory and vanishes with the
# instance; this is mounted over /app/data instead.
resource "google_storage_bucket" "data" {
  name                        = "${var.project_id}-researchit-data"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
}

resource "google_storage_bucket_iam_member" "api_data" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.api.email}"
}

# --- Services -------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name                 = "researchit-api"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_ALL"
  deletion_protection  = var.deletion_protection
  invoker_iam_disabled = var.public

  template {
    service_account = google_service_account.api.email
    # Gen2 is what mounts a Cloud Storage bucket as a volume.
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    # A research run streams its progress over one request for minutes.
    timeout = "3600s"

    # One instance: jobs and rate-limit counters live in process memory, so
    # a second instance would split both. See ARCHITECTURE.md, Known limits.
    scaling {
      min_instance_count = var.api_min_instances
      max_instance_count = 1
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    volumes {
      name = "data"
      gcs {
        bucket    = google_storage_bucket.data.name
        read_only = false
        # The image runs as uid 10001; see be-main/Dockerfile.
        mount_options = ["uid=10001", "gid=10001"]
      }
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        # A job keeps working after its request ends, which it cannot do on
        # CPU that is only allocated during requests.
        cpu_idle          = false
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      volume_mounts {
        name       = "data"
        mount_path = "/app/data"
      }

      # Migrations run at boot, so give startup longer than a request.
      startup_probe {
        http_get {
          path = "/health"
        }
        period_seconds    = 5
        failure_threshold = 24
      }
    }
  }

  lifecycle {
    # Cloud Build rolls out images; Terraform owns everything else.
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [
    google_project_iam_member.api,
    google_secret_manager_secret_iam_member.api_reads_database_url,
    google_secret_manager_secret_version.database_url,
    google_storage_bucket_iam_member.api_data,
  ]
}

resource "google_cloud_run_v2_service" "web" {
  name                 = "researchit-web"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_ALL"
  deletion_protection  = var.deletion_protection
  invoker_iam_disabled = var.public

  template {
    service_account = google_service_account.web.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      # The API's URL is baked into this image at build time; see
      # deploy/gcp/cloudbuild.yaml.
      image = var.web_image

      ports {
        container_port = 3000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.enabled]
}
