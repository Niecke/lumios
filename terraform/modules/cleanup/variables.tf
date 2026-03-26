variable "region" {
  description = "GCP region"
  type        = string
}

variable "project_id" {
  description = "GCP project ID"
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
  description = "Full container image URL including tag (same as backend)"
  type        = string
}

variable "vm_internal_ip" {
  description = "Internal IP of the VM running Postgres"
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

variable "gcs_hmac_access_key_secret_id" {
  description = "Secret Manager secret ID for the GCS HMAC access key"
  type        = string
}

variable "gcs_hmac_secret_secret_id" {
  description = "Secret Manager secret ID for the GCS HMAC secret"
  type        = string
}
