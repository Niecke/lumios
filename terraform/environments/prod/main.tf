module "apis" {
  source = "../../modules/apis"
}

module "network" {
  source      = "../../modules/network"
  region      = var.region
  subnet_cidr = "10.0.0.0/24"

  depends_on = [module.apis]
}

module "artifact_registry" {
  source = "../../modules/artifact_registry"
  region = var.region

  depends_on = [module.apis]
}

module "storage" {
  source     = "../../modules/storage"
  region     = var.region
  project_id = var.project_id
}

module "secrets" {
  source = "../../modules/secrets"

  depends_on = [module.apis]
}

module "vm" {
  source                      = "../../modules/vm"
  zone                        = var.zone
  network_self_link           = module.network.network_self_link
  subnet_self_link            = module.network.subnet_self_link
  postgres_password_secret_id = module.secrets.postgres_password_secret_id
  subnet_cidr                 = "10.0.0.0/24"

  depends_on = [module.apis, module.network, module.secrets]
}

module "cloudrun" {
  source                              = "../../modules/cloudrun"
  region                              = var.region
  network_id                          = module.network.network_id
  subnet_id                           = module.network.subnet_id
  image                               = "europe-west1-docker.pkg.dev/${var.project_id}/lumios/backend:latest"
  frontend_image                      = "europe-west1-docker.pkg.dev/${var.project_id}/lumios/frontend:latest"
  landingpage_image                   = "europe-west1-docker.pkg.dev/${var.project_id}/lumios/landingpage:latest"
  vm_internal_ip                      = module.vm.internal_ip
  photos_bucket_name                  = module.storage.photos_bucket_name
  postgres_password_secret_id         = module.secrets.postgres_password_secret_id
  secret_key_secret_id                = module.secrets.secret_key_secret_id
  jwt_secret_secret_id                = module.secrets.jwt_secret_secret_id
  init_admin_password_secret_id       = module.secrets.init_admin_password_secret_id
  google_client_id_secret_id          = module.secrets.google_client_id_secret_id
  google_client_secret_secret_id      = module.secrets.google_client_secret_secret_id
  google_frontend_client_id_secret_id = module.secrets.google_frontend_client_id_secret_id
  brevo_api_key_secret_id             = module.secrets.brevo_api_key_secret_id
  admin_email                         = "daniel@niecke-it.de"
  project_id                          = var.project_id
  public_base_url                     = "https://lumios-api.niecke-it.de"
  frontend_url                        = "https://lumios-app.niecke-it.de"
  landingpage_domain                  = "lumios.niecke-it.de"

  depends_on = [module.apis, module.network, module.vm, module.secrets, module.storage]
}

module "cleanup" {
  source = "../../modules/cleanup"

  region                        = var.region
  project_id                    = var.project_id
  network_id                    = module.network.network_id
  subnet_id                     = module.network.subnet_id
  image                         = "europe-west1-docker.pkg.dev/${var.project_id}/lumios/backend:latest"
  vm_internal_ip                = module.vm.internal_ip
  photos_bucket_name            = module.storage.photos_bucket_name
  postgres_password_secret_id   = module.secrets.postgres_password_secret_id
  secret_key_secret_id          = module.secrets.secret_key_secret_id
  jwt_secret_secret_id          = module.secrets.jwt_secret_secret_id
  gcs_hmac_access_key_secret_id = module.cloudrun.gcs_hmac_access_key_secret_id
  gcs_hmac_secret_secret_id     = module.cloudrun.gcs_hmac_secret_secret_id

  depends_on = [module.apis, module.network, module.vm, module.secrets, module.storage, module.cloudrun]
}

module "monitoring" {
  source               = "../../modules/monitoring"
  project_id           = var.project_id
  notification_email   = "daniel@niecke-it.de"
  backend_domain       = "lumios-api.niecke-it.de"
  frontend_domain      = "lumios-app.niecke-it.de"
  landingpage_domain   = "lumios.niecke-it.de"
  enable_uptime_checks = false

  depends_on = [module.apis, module.cloudrun]
}
