# Mirrors scripts/cognito-bootstrap.sh's dev pool exactly, under Terraform
# instead of a hand-run script — see docs/ARCHITECTURE.md's Decisions for
# why Cognito itself (unlike S3/SQS) is never emulated, dev or prod.
resource "aws_cognito_user_pool" "prod" {
  name                     = var.cognito_pool_name
  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]
}

resource "aws_cognito_user_pool_client" "web" {
  name                = var.cognito_client_name
  user_pool_id        = aws_cognito_user_pool.prod.id
  generate_secret     = false # public client — same as the dev pool, no secret a browser could hide anyway
  explicit_auth_flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}
