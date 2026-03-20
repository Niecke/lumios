variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "notification_email" {
  description = "Email address for uptime check alerts"
  type        = string
}

variable "backend_domain" {
  description = "Domain of the backend service (e.g. backend.lumios.niecke-it.de)"
  type        = string
}

variable "frontend_domain" {
  description = "Domain of the frontend service (e.g. app.lumios.niecke-it.de)"
  type        = string
}

variable "landingpage_domain" {
  description = "Domain of the landing page (e.g. lumios.niecke-it.de)"
  type        = string
}
