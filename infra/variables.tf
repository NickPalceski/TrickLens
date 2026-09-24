variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "github_repo" {
  description = "owner/repo, used to scope the GitHub OIDC trust policies."
  type        = string
  default     = "NickPalceski/TrickLens"
}

# --- Image ------------------------------------------------------------------

variable "ecr_repo_name" {
  type    = string
  default = "tricklens"
}

variable "image_tag" {
  description = <<-EOT
    Immutable tag (the deploying git SHA) of the image all 3 Lambda
    functions point at. Defaults to "bootstrap" only so the very first
    `terraform apply -target=aws_ecr_repository.main` (before any real image
    has ever been pushed, see README's Deployment section) doesn't require
    -var — every real deploy passes this explicitly.
  EOT
  type        = string
  default     = "bootstrap"
}

# --- Secrets (never written to a committed .tfvars) --------------------------

variable "database_url" {
  description = "asyncpg-flavored Neon connection string. Stored in SSM, not a plain Lambda env var — see docs/ARCHITECTURE.md's Decisions."
  type        = string
  sensitive   = true
}

# --- Cognito ------------------------------------------------------------------

variable "cognito_pool_name" {
  type    = string
  default = "tricklens-prod"
}

variable "cognito_client_name" {
  type    = string
  default = "tricklens-web"
}

# --- API ------------------------------------------------------------------

variable "cors_origins" {
  description = "Comma-separated allowed origins. Placeholder until step 4's frontend has a real deployed URL."
  type        = string
  default     = "http://localhost:3000"
}

# --- Rankings schedule -------------------------------------------------------

variable "rankings_schedule_expression" {
  description = "EventBridge schedule expression for the Discover rankings rebuild."
  type        = string
  default     = "rate(30 minutes)"
}

# --- Budget -------------------------------------------------------------------

variable "budget_email" {
  description = "Notified at 80%/100% of the $5/mo budget threshold."
  type        = string
}
