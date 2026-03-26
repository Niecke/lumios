# ---------------------------------------------------------------------------
# Cleanup Job — daily hard-delete of soft-deleted accounts (30-day retention)
#
# Reuses the backend Docker image; just overrides CMD to run the Flask CLI
# command instead of Gunicorn. Cloud Scheduler triggers the job at 02:00 UTC.
#
# Cost: Cloud Run Jobs free tier covers 180,000 vCPU-seconds/month.
# A ~30s daily run uses ~900 vCPU-seconds/month — well within free tier.
# Cloud Scheduler: $0.10/job/month after the 3-job free tier.
# ---------------------------------------------------------------------------

# Dedicated service account for the cleanup job (least-privilege)
resource "google_service_account" "cleanup_job" {
  account_id   = "lumios-cleanup-job"
  display_name = "Lumios Cleanup Job"
}

# Service account that Cloud Scheduler uses to invoke the job
resource "google_service_account" "cleanup_scheduler" {
  account_id   = "lumios-cleanup-scheduler"
  display_name = "Lumios Cleanup Scheduler"
}

# ---------------------------------------------------------------------------
# Secret Manager access — only the secrets required at runtime
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret_iam_member" "cleanup_postgres_password" {
  secret_id = var.postgres_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cleanup_job.email}"
}

resource "google_secret_manager_secret_iam_member" "cleanup_secret_key" {
  secret_id = var.secret_key_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cleanup_job.email}"
}

resource "google_secret_manager_secret_iam_member" "cleanup_jwt_secret" {
  secret_id = var.jwt_secret_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cleanup_job.email}"
}

resource "google_secret_manager_secret_iam_member" "cleanup_gcs_hmac_access_key" {
  secret_id = var.gcs_hmac_access_key_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cleanup_job.email}"
}

resource "google_secret_manager_secret_iam_member" "cleanup_gcs_hmac_secret" {
  secret_id = var.gcs_hmac_secret_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cleanup_job.email}"
}

# GCS object deletion
resource "google_storage_bucket_iam_member" "cleanup_photos" {
  bucket = var.photos_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cleanup_job.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run Job
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_job" "cleanup" {
  name     = "lumios-cleanup"
  location = var.region

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }

  template {
    template {
      service_account = google_service_account.cleanup_job.email
      max_retries     = 3

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = var.network_id
          subnetwork = var.subnet_id
        }
      }

      containers {
        # Same image as the backend service — CMD is overridden below
        image   = var.image
        command = ["python", "-m", "flask", "purge-deleted-accounts"]

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
          name  = "S3_ENDPOINT_URL"
          value = "https://storage.googleapis.com"
        }
        env {
          name  = "S3_BUCKET"
          value = var.photos_bucket_name
        }
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
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
          name = "S3_ACCESS_KEY"
          value_source {
            secret_key_ref {
              secret  = var.gcs_hmac_access_key_secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "S3_SECRET_KEY"
          value_source {
            secret_key_ref {
              secret  = var.gcs_hmac_secret_secret_id
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
}

# ---------------------------------------------------------------------------
# Cloud Scheduler — triggers the job at 02:00 UTC every day
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  name     = google_cloud_run_v2_job.cleanup.name
  location = google_cloud_run_v2_job.cleanup.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cleanup_scheduler.email}"
}

resource "google_cloud_scheduler_job" "cleanup_daily" {
  name             = "lumios-cleanup-daily"
  description      = "Trigger the Lumios cleanup Cloud Run Job at 02:00 UTC"
  schedule         = "0 2 * * *"
  time_zone        = "UTC"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 3
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.cleanup.name}:run"

    oauth_token {
      service_account_email = google_service_account.cleanup_scheduler.email
    }
  }
}
