output "photos_bucket_name" {
  description = "Name of the photos GCS bucket"
  value       = google_storage_bucket.photos.name
}
