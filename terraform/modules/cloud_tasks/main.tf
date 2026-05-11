resource "google_cloud_tasks_queue" "video_process" {
  name     = "lumios-video-process"
  location = var.location

  rate_limits {
    max_concurrent_dispatches = 5
    max_dispatches_per_second  = 2
  }

  retry_config {
    max_attempts = 3
    min_backoff  = "10s"
    max_backoff  = "300s"
  }
}

resource "google_cloud_tasks_queue_iam_member" "cloudrun_enqueue" {
  name     = google_cloud_tasks_queue.video_process.name
  location = var.location
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${var.cloudrun_service_account_email}"
}
