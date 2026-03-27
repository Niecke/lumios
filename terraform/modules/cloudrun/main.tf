resource "google_service_account" "cloudrun" {
  account_id   = "lumios-cloudrun"
  display_name = "Lumios Cloud Run"
}

resource "google_service_account" "cloudrun_frontend" {
  account_id   = "lumios-cloudrun-frontend"
  display_name = "Lumios Cloud Run Frontend"
}

resource "google_service_account" "cloudrun_landingpage" {
  account_id   = "lumios-cloudrun-landingpage"
  display_name = "Lumios Cloud Run Landingpage"
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

resource "google_secret_manager_secret_iam_member" "cloudrun_brevo_api_key" {
  secret_id = var.brevo_api_key_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_project_iam_member" "cloudrun_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_storage_bucket_iam_member" "cloudrun_photos" {
  bucket = var.photos_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloudrun.email}"
}

# Allow the Terraform SA to create HMAC keys for the Cloud Run SA
data "google_client_openid_userinfo" "terraform" {}

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

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  template {
    service_account = google_service_account.cloudrun.email

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = var.network_id
        subnetwork = var.subnet_id
      }
    }

    containers {
      image = var.image

      env {
        name  = "GUNICORN_WORKERS"
        value = "2"
      }
      env {
        name  = "POSTGRES_HOST"
        value = var.vm_internal_ip
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
        name = "POSTGRES_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.postgres_password_secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "PUBLIC_BASE_URL"
        value = var.public_base_url
      }
      env {
        name  = "FRONTEND_URL"
        value = var.frontend_url
      }
      env {
        name  = "REDIS_URL"
        value = "redis://${var.vm_internal_ip}:6379"
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
        name  = "CLOUD_TRACE_ENABLED"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "S3_ENDPOINT_URL"
        value = "https://storage.googleapis.com"
      }
      env {
        name = "S3_ACCESS_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gcs_hmac_access_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "S3_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gcs_hmac_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "S3_BUCKET"
        value = var.photos_bucket_name
      }
      env {
        name = "BREVO_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.brevo_api_key_secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "ADMIN_EMAIL"
        value = var.admin_email
      }
      env {
        name  = "LANDINGPAGE_URL"
        value = var.landingpage_url
      }
      env {
        name  = "BREVO_WAITLIST_LIST_ID"
        value = "4"
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

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  name     = google_cloud_run_v2_service.frontend.name
  location = google_cloud_run_v2_service.frontend.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "frontend" {
  name                = "lumios-frontend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  template {
    service_account = google_service_account.cloudrun_frontend.email

    scaling {
      max_instance_count = 2
    }

    containers {
      image = var.frontend_image

      env {
        name  = "BACKEND_URL"
        value = var.public_base_url
      }

      env {
        name  = "BACKEND_HOST"
        value = replace(var.public_base_url, "https://", "")
      }

      env {
        name  = "S3_ENDPOINT_URL"
        value = "https://storage.googleapis.com"
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

resource "google_cloud_run_v2_service_iam_member" "landingpage_public" {
  name     = google_cloud_run_v2_service.landingpage.name
  location = google_cloud_run_v2_service.landingpage.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "landingpage" {
  name                = "lumios-landingpage"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  template {
    service_account = google_service_account.cloudrun_landingpage.email

    scaling {
      max_instance_count = 2
    }

    containers {
      image = var.landingpage_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
}

resource "google_cloud_run_domain_mapping" "backend" {
  name     = trimprefix(var.public_base_url, "https://")
  location = var.region

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.backend.name
  }
}

resource "google_cloud_run_domain_mapping" "frontend" {
  name     = trimprefix(var.frontend_url, "https://")
  location = var.region

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.frontend.name
  }
}

resource "google_cloud_run_domain_mapping" "landingpage" {
  name     = var.landingpage_domain
  location = var.region

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.landingpage.name
  }
}
