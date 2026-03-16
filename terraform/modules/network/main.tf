resource "google_compute_network" "lumios" {
  name                    = "lumios"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "lumios" {
  name          = "lumios-${var.region}"
  network       = google_compute_network.lumios.id
  region        = var.region
  ip_cidr_range = var.subnet_cidr
}
