module "apis" {
  source = "../../modules/apis"
}

module "network" {
  source      = "../../modules/network"
  region      = var.region
  subnet_cidr = "10.0.0.0/24"

  depends_on = [module.apis]
}
