variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "github_oidc_sub_prefix" {
  description = <<-EOT
    Prefix of the `sub` claim GitHub puts in this repo's Actions OIDC
    tokens, used to scope the OIDC trust policies. This repo has GitHub's
    immutable subject format enabled, so it is `repo:<owner>@<owner_id>/<repo>@<repo_id>`,
    NOT the plain `repo:<owner>/<repo>` most docs show — a mismatch here fails
    as a bare "Not authorized to perform sts:AssumeRoleWithWebIdentity".
    Source of truth: `curl -s https://api.github.com/repos/NickPalceski/TrickLens/actions/oidc/customization/sub`
    (the `sub_claim_prefix` field).
  EOT
  type        = string
  default     = "repo:NickPalceski@128099643/TrickLens@1306046704"
}

# --- Image ------------------------------------------------------------------

variable "ecr_repo_name" {
  type    = string
  default = "tricklens"
}

variable "ecr_worker_repo_name" {
  type    = string
  default = "tricklens-worker"
}

variable "image_tag" {
  description = <<-EOT
    Immutable tag (the deploying git SHA) of the images all 3 Lambda
    functions point at: the API image (`ecr_repo_name`) for api/rankings,
    the worker image (`ecr_worker_repo_name`, step 6a) for the worker. CI
    pushes both under the same SHA. Defaults to "bootstrap" only so the very first
    `terraform apply -target=aws_ecr_repository.main` (before any real image
    has ever been pushed, see docs/deployment.md) doesn't require
    -var — every real deploy passes this explicitly.
  EOT
  type        = string
  default     = "bootstrap"
}

# --- Secrets (never written to a committed .tfvars) --------------------------

variable "database_url" {
  description = "asyncpg-flavored Neon connection string. Stored in SSM, not a plain Lambda env var — see docs/components/services.md."
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

variable "domain_name" {
  description = "The registered domain (Route 53, hosted zone created with the registration). The web app is served at its apex; api., www. and media. hang off it (infra/domain.tf)."
  type        = string
  default     = "tricklens.com"
}

variable "extra_cors_origins" {
  description = "Origins allowed to call the prod API besides https://<domain_name>. Empty: a local web app talks to the local API, never prod."
  type        = list(string)
  default     = []
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

variable "worker_max_concurrency" {
  description = "Most worker runs at once (the SQS trigger's maximum concurrency, 2-1000): the spend ceiling. Clips past it wait in the queue."
  type        = number
  # The account's whole Lambda concurrency was 10 when this was set
  # (2026-10-17), shared with the API and rankings, so the worker gets half.
  # At 30-120s a clip, 5 at once still clears 150-600 clips an hour.
  default = 5
}
