# Deliberately empty — bucket/table names are account-specific (S3 bucket
# names are globally unique, so scripts/terraform-bootstrap.sh suffixes the
# bucket with the AWS account id) and can't be interpolated here; Terraform
# backend blocks only accept literal values. Every `terraform init` on every
# machine passes -backend-config=backend.hcl (see that file, generated once
# by scripts/terraform-bootstrap.sh and committed — it holds no secrets,
# just names).
#
# This bucket/table are deliberately NOT managed by this Terraform config —
# a backend can't safely manage the store it's sitting in, same reasoning as
# the Cognito dev pool staying outside Terraform forever (see CLAUDE.md).
terraform {
  backend "s3" {}
}
