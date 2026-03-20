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
