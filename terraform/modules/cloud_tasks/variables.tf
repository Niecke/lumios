variable "location" {
  description = "GCP region for the Cloud Tasks queue"
  type        = string
}

variable "cloudrun_service_account_email" {
  description = "Service account email of the Cloud Run backend (enqueuer)"
  type        = string
}
