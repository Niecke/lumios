resource "google_service_account" "vm" {
  account_id   = "lumios-vm"
  display_name = "Lumios VM (Postgres + Redis)"
}

resource "google_compute_disk" "data" {
  name = "lumios-data"
  type = "pd-ssd"
  zone = var.zone
  size = var.disk_size_gb
}

resource "google_compute_instance" "vm" {
  name         = "lumios-vm"
  machine_type = var.machine_type
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-13"
      size  = 20
      type  = "pd-standard"
    }
  }

  attached_disk {
    source      = google_compute_disk.data.self_link
    device_name = "lumios-data"
  }

  network_interface {
    subnetwork = var.subnet_self_link
    # public ip neede for installing software since Cloud NAT would cost >$32/month
    access_config {}
  }

  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    startup-script = file("${path.module}/startup.sh")
  }

  tags = ["lumios-vm"]
}

# Allow Postgres and Redis only from within the VPC
resource "google_compute_firewall" "allow_db" {
  name    = "lumios-allow-db-internal"
  network = var.network_self_link

  allow {
    protocol = "tcp"
    ports    = ["5432", "6379"]
  }

  source_ranges = [var.subnet_cidr]
  target_tags   = ["lumios-vm"]
}

resource "google_secret_manager_secret_iam_member" "vm_postgres_password" {
  secret_id = var.postgres_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.vm.email}"
}

# Allow SSH via IAP only (no public SSH)
resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "lumios-allow-iap-ssh"
  network = var.network_self_link

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"] # Google IAP range
  target_tags   = ["lumios-vm"]
}
