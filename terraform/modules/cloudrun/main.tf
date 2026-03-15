resource "google_service_account" "cloudrun" {
  account_id   = "lumios-cloudrun"
  display_name = "Lumios Cloud Run"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_postgres_password" {
  secret_id = var.postgres_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_secret_key" {
  secret_id = var.secret_key_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_jwt_secret" {
  secret_id = var.jwt_secret_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_init_admin_password" {
  secret_id = var.init_admin_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_google_client_id" {
  secret_id = var.google_client_id_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_google_client_secret" {
  secret_id = var.google_client_secret_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_google_frontend_client_id" {
  secret_id = var.google_frontend_client_id_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_storage_bucket_iam_member" "cloudrun_photos" {
  bucket = var.photos_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloudrun.email}"
}

# HMAC keys for S3-compatible GCS access (boto3/minio compatibility).
# Created manually — Terraform manages the secrets and IAM grants only.
# To create/rotate:
#   gcloud storage hmac create lumios-cloudrun@<PROJECT_ID>.iam.gserviceaccount.com
#   echo -n "ACCESS_ID" | gcloud secrets versions add lumios-gcs-hmac-access-key --data-file=-
#   echo -n "SECRET"    | gcloud secrets versions add lumios-gcs-hmac-secret --data-file=-
resource "google_secret_manager_secret" "gcs_hmac_access_key" {
  secret_id = "lumios-gcs-hmac-access-key"
  replication { 
    auto {} 
    }
}

resource "google_secret_manager_secret" "gcs_hmac_secret" {
  secret_id = "lumios-gcs-hmac-secret"
  replication { 
    auto {} 
    }
}

resource "google_secret_manager_secret_iam_member" "cloudrun_gcs_hmac_access_key" {
  secret_id = google_secret_manager_secret.gcs_hmac_access_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_secret_manager_secret_iam_member" "cloudrun_gcs_hmac_secret" {
  secret_id = google_secret_manager_secret.gcs_hmac_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.backend.name
  location = google_cloud_run_v2_service.backend.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "backend" {
  name                = "lumios-backend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.cloudrun.email

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = var.network_id
        subnetwork = var.subnet_id
      }
    }

    scaling {
      max_instance_count = 2
    }

    containers {
      image = var.image

      env {
        name  = "PUBLIC_BASE_URL"
        value = var.public_base_url
      }
      env {
        name  = "POSTGRES_HOST"
        value = var.vm_internal_ip
      }
      env {
        name  = "REDIS_URL"
        value = "redis://${var.vm_internal_ip}:6379"
      }
      env {
        name  = "POSTGRES_USER"
        value = "lumios"
      }
      env {
        name  = "POSTGRES_DB"
        value = "lumios"
      }
      env {
        name  = "GCS_BUCKET_PHOTOS"
        value = var.photos_bucket_name
      }
      env {
        name  = "FRONTEND_URL"
        value = var.frontend_url
      }
      env {
        name = "POSTGRES_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.postgres_password_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_key_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = var.jwt_secret_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "INIT_ADMIN_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.init_admin_password_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_CLIENT_ID"
        value_source {
          secret_key_ref {
            secret  = var.google_client_id_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = var.google_client_secret_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_FRONTEND_CLIENT_ID"
        value_source {
          secret_key_ref {
            secret  = var.google_frontend_client_id_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GCS_HMAC_ACCESS_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gcs_hmac_access_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GCS_HMAC_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gcs_hmac_secret.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
}
