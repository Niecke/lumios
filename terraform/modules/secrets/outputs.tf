output "postgres_password_secret_id" {
  description = "Secret Manager secret ID for the Postgres password"
  value       = google_secret_manager_secret.postgres_password.secret_id
}

output "secret_key_secret_id" {
  description = "Secret Manager secret ID for the Flask secret key"
  value       = google_secret_manager_secret.secret_key.secret_id
}

output "jwt_secret_secret_id" {
  description = "Secret Manager secret ID for the JWT secret"
  value       = google_secret_manager_secret.jwt_secret.secret_id
}

output "init_admin_password_secret_id" {
  description = "Secret Manager secret ID for the initial admin password"
  value       = google_secret_manager_secret.init_admin_password.secret_id
}

output "google_client_id_secret_id" {
  description = "Secret Manager secret ID for the Google OAuth client ID"
  value       = google_secret_manager_secret.google_client_id.secret_id
}

output "google_client_secret_secret_id" {
  description = "Secret Manager secret ID for the Google OAuth client secret"
  value       = google_secret_manager_secret.google_client_secret.secret_id
}
