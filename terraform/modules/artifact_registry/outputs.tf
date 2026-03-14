output "repository_url" {
  description = "Base URL of the Docker repository"
  value       = "${var.region}-docker.pkg.dev/${google_artifact_registry_repository.lumios.project}/${google_artifact_registry_repository.lumios.repository_id}"
}
