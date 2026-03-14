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

  depends_on = [module.apis, module.network, module.secrets]
}
