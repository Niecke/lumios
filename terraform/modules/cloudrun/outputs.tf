output "backend_service_url" {
  description = "URL of the backend Cloud Run service"
  value       = google_cloud_run_v2_service.backend.uri
}

output "frontend_service_url" {
  description = "URL of the frontend Cloud Run service"
  value       = google_cloud_run_v2_service.frontend.uri
}

output "landingpage_service_url" {
  description = "URL of the landing page Cloud Run service"
  value       = google_cloud_run_v2_service.landingpage.uri
}

output "gcs_hmac_access_key_secret_id" {
  description = "Secret Manager secret ID for the GCS HMAC access key"
  value       = google_secret_manager_secret.gcs_hmac_access_key.secret_id
}

output "gcs_hmac_secret_secret_id" {
  description = "Secret Manager secret ID for the GCS HMAC secret"
  value       = google_secret_manager_secret.gcs_hmac_secret.secret_id
}
