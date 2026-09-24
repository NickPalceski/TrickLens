provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "tricklens"
      Env       = "prod"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
