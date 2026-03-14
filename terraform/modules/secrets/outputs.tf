output "postgres_password_secret_id" {
  description = "Secret Manager secret ID for the Postgres password"
  value       = google_secret_manager_secret.postgres_password.secret_id
}
