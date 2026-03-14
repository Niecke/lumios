resource "random_password" "postgres" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "google_secret_manager_secret" "postgres_password" {
  secret_id = "lumios-postgres-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "postgres_password" {
  secret      = google_secret_manager_secret.postgres_password.id
  secret_data = random_password.postgres.result
}

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "random_password" "init_admin_password" {
  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+?"
}

resource "google_secret_manager_secret" "secret_key" {
  secret_id = "lumios-secret-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "secret_key" {
  secret      = google_secret_manager_secret.secret_key.id
  secret_data = random_password.secret_key.result
}

resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "lumios-jwt-secret"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "jwt_secret" {
  secret      = google_secret_manager_secret.jwt_secret.id
  secret_data = random_password.jwt_secret.result
}

resource "google_secret_manager_secret" "init_admin_password" {
  secret_id = "lumios-init-admin-password"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "init_admin_password" {
  secret      = google_secret_manager_secret.init_admin_password.id
  secret_data = random_password.init_admin_password.result
}

# OAuth credentials — created manually in Google Cloud Console.
# After creating an OAuth 2.0 client, add the values with:
#   gcloud secrets versions add lumios-google-client-id --data-file=-
#   gcloud secrets versions add lumios-google-client-secret --data-file=-
resource "google_secret_manager_secret" "google_client_id" {
  secret_id = "lumios-google-client-id"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "google_client_secret" {
  secret_id = "lumios-google-client-secret"
  replication {
    auto {}
  }
}
