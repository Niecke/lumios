variable "zone" {
  description = "GCP zone for the VM"
  type        = string
}

variable "network_self_link" {
  description = "Self-link of the VPC network"
  type        = string
}

variable "subnet_self_link" {
  description = "Self-link of the subnet"
  type        = string
}

variable "machine_type" {
  description = "GCE machine type"
  type        = string
  default     = "e2-small"
}

variable "disk_size_gb" {
  description = "Size of the persistent data disk in GB"
  type        = number
  default     = 50
}

variable "postgres_password_secret_id" {
  description = "Secret Manager secret ID for the Postgres password"
  type        = string
}
