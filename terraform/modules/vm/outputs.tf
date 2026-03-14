output "internal_ip" {
  description = "Internal IP address of the VM"
  value       = google_compute_instance.vm.network_interface[0].network_ip
}

output "service_account_email" {
  description = "Service account email of the VM"
  value       = google_service_account.vm.email
}
