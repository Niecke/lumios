variable "region" {
  description = "GCP region"
  type        = string
}

variable "network_id" {
  description = "VPC network ID"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID for Direct VPC Egress"
  type        = string
}

variable "image" {
  description = "Full container image URL including tag"
  type        = string
}

variable "vm_internal_ip" {
  description = "Internal IP of the VM running Postgres and Redis"
  type        = string
}

variable "photos_bucket_name" {
  description = "GCS bucket name for photo storage"
  type        = string
}

variable "postgres_password_secret_id" {
  description = "Secret Manager secret ID for the Postgres password"
  type        = string
}

variable "secret_key_secret_id" {
  description = "Secret Manager secret ID for the Flask secret key"
  type        = string
}

variable "jwt_secret_secret_id" {
  description = "Secret Manager secret ID for the JWT secret"
  type        = string
}

variable "init_admin_password_secret_id" {
  description = "Secret Manager secret ID for the initial admin password"
  type        = string
}

variable "google_client_id_secret_id" {
  description = "Secret Manager secret ID for the Google OAuth client ID"
  type        = string
}

variable "google_client_secret_secret_id" {
  description = "Secret Manager secret ID for the Google OAuth client secret"
  type        = string
}

variable "google_frontend_client_id_secret_id" {
  description = "Secret Manager secret ID for the Google OAuth frontend client ID"
  type        = string
}

variable "frontend_image" {
  description = "Full container image URL for the frontend including tag"
  type        = string
}

variable "public_base_url" {
  description = "Public base URL of the Cloud Run service"
  type        = string
}

variable "frontend_url" {
  description = "Public URL of the frontend app (used for redirects after OAuth callbacks)"
  type        = string
}
