# See docs/ARCHITECTURE.md's Decisions and app/services/secrets.py: DATABASE_URL
# is a SecureString here, not a plain Lambda env var, to keep a full Postgres
# connection string out of the Lambda console's plaintext config view.
resource "aws_ssm_parameter" "database_url" {
  name  = "/tricklens/prod/database_url"
  type  = "SecureString"
  value = var.database_url
}
