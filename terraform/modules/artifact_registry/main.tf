resource "google_artifact_registry_repository" "lumios" {
  repository_id = "lumios"
  location      = var.region
  format        = "DOCKER"
  description   = "Lumios container images (backend, frontend)"
}
