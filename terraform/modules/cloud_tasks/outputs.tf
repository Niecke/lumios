output "queue_name" {
  description = "Short name of the Cloud Tasks queue (used as CLOUD_TASKS_QUEUE env var)"
  value       = google_cloud_tasks_queue.video_process.name
}
