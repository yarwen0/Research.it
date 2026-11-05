output "api_url" {
  description = "The API. The web image must be built with this as NEXT_PUBLIC_API_URL."
  value       = google_cloud_run_v2_service.api.uri
}

output "web_url" {
  description = "The web frontend."
  value       = google_cloud_run_v2_service.web.uri
}

output "image_repository" {
  description = "Where Cloud Build pushes images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "deployer_service_account" {
  description = "Run Cloud Build as this identity; it can push images and roll out revisions, nothing more."
  value       = google_service_account.deployer.email
}

output "cloud_sql_connection_name" {
  description = "For connecting with the Cloud SQL Auth Proxy from a workstation."
  value       = google_sql_database_instance.main.connection_name
}

output "data_bucket" {
  value = google_storage_bucket.data.name
}
