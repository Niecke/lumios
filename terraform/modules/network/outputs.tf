output "network_id" {
  description = "ID of the VPC network"
  value       = google_compute_network.lumios.id
}

output "network_self_link" {
  description = "Self-link of the VPC network"
  value       = google_compute_network.lumios.self_link
}

output "subnet_id" {
  description = "ID of the subnet"
  value       = google_compute_subnetwork.lumios.id
}

output "subnet_self_link" {
  description = "Self-link of the subnet"
  value       = google_compute_subnetwork.lumios.self_link
}
