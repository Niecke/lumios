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
  source                         = "../../modules/cloudrun"
  region                         = var.region
  network_id                     = module.network.network_id
  subnet_id                      = module.network.subnet_id
  image                          = "europe-west1-docker.pkg.dev/${var.project_id}/lumios/backend:latest"
  vm_internal_ip                 = module.vm.internal_ip
  photos_bucket_name             = module.storage.photos_bucket_name
  postgres_password_secret_id    = module.secrets.postgres_password_secret_id
  secret_key_secret_id           = module.secrets.secret_key_secret_id
  jwt_secret_secret_id           = module.secrets.jwt_secret_secret_id
  init_admin_password_secret_id  = module.secrets.init_admin_password_secret_id
  google_client_id_secret_id     = module.secrets.google_client_id_secret_id
  google_client_secret_secret_id = module.secrets.google_client_secret_secret_id

  depends_on = [module.apis, module.network, module.vm, module.secrets, module.storage]
}
