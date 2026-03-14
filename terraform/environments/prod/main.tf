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
