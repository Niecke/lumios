resource "google_storage_bucket" "photos" {
  name                        = "lumios-photos-${var.project_id}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true

  cors {
    origin          = ["https://lumios-app.niecke-it.de"]
    method          = ["GET", "PUT", "HEAD"]
    response_header = ["Content-Type", "ETag"]
    max_age_seconds = 3600
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 730
    }
    action {
      type = "Delete"
    }
  }
}
