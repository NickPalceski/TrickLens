# =============================================================================
# Lambda execution roles — one per function, least privilege matching only
# what each actually calls today (confirmed against app/services/storage.py,
# queue.py, auth.py). See docs/ARCHITECTURE.md's Decisions for why the
# worker role has no S3 permissions yet: the stub worker never touches S3,
# and step 6 must add s3:GetObject/PutObject when the real analyzer starts
# reading raw/ and writing processed/thumbs/ — permissions aren't
# front-loaded for code that doesn't exist yet.
# =============================================================================

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# All three Lambdas read DATABASE_URL from SSM (see secrets.tf) — every
# function's role needs this, regardless of what else it does.
data "aws_iam_policy_document" "ssm_database_url_read" {
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.database_url.arn]
  }
}

# --- API ----------------------------------------------------------------------

resource "aws_iam_role" "api_lambda" {
  name               = "tricklens-api-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "api_basic_execution" {
  role       = aws_iam_role.api_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "api_lambda_policy" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.media.arn, "${aws_s3_bucket.media.arn}/*"]
  }
  statement {
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.analysis.arn]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.database_url.arn]
  }
}

resource "aws_iam_role_policy" "api_lambda" {
  name   = "tricklens-api-lambda"
  role   = aws_iam_role.api_lambda.id
  policy = data.aws_iam_policy_document.api_lambda_policy.json
}

# --- Worker ---------------------------------------------------------------

resource "aws_iam_role" "worker_lambda" {
  name               = "tricklens-worker-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "worker_basic_execution" {
  role       = aws_iam_role.worker_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "worker_lambda_policy" {
  statement {
    # The Lambda event-source-mapping itself calls receive/delete on the
    # worker's behalf, but the execution role still needs these permissions
    # granted directly — AWS just invokes them under this role.
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.analysis.arn]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.database_url.arn]
  }
}

resource "aws_iam_role_policy" "worker_lambda" {
  name   = "tricklens-worker-lambda"
  role   = aws_iam_role.worker_lambda.id
  policy = data.aws_iam_policy_document.worker_lambda_policy.json
}

# --- Rankings ---------------------------------------------------------------

resource "aws_iam_role" "rankings_lambda" {
  name               = "tricklens-rankings-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "rankings_basic_execution" {
  role       = aws_iam_role.rankings_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# app/rankings.py touches only Postgres — no AWS API calls beyond reading
# its own DB secret out of SSM.
resource "aws_iam_role_policy" "rankings_lambda" {
  name   = "tricklens-rankings-lambda"
  role   = aws_iam_role.rankings_lambda.id
  policy = data.aws_iam_policy_document.ssm_database_url_read.json
}

# =============================================================================
# GitHub Actions OIDC — no static AWS keys stored in GitHub. Two roles:
# a broad deploy role (main branch only) and a narrow read-only plan role
# (PRs, including forks). See docs/ARCHITECTURE.md's Decisions for why the
# deploy role's breadth is accepted rather than avoided: Terraform apply IS
# the thing creating/mutating this infra, and the actual safety net is the
# $5 AWS Budget alarm (budget.tf), not IAM scoping.
# =============================================================================

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # SHA1 fingerprint of token.actions.githubusercontent.com's current TLS
  # root CA (fetched directly via openssl, not hand-copied from a
  # tutorial — those certs rotate). AWS has trusted GitHub's actual signing
  # certs directly since April 2022 regardless of this value, but the field
  # is still required and must be well-formed. If this ever needs
  # refreshing: `openssl s_client -connect token.actions.githubusercontent.com:443
  # -showcerts | openssl x509 -fingerprint -sha1 -noout` on the last cert in
  # the chain.
  thumbprint_list = ["ab9d0263244dd0326eb67015705a667e79cfe998"]
}

data "aws_iam_policy_document" "gha_deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_oidc_sub_prefix}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "gha_plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      # GitHub's sub claim for a pull_request-triggered workflow run, not
      # per-PR-number — every PR from this repo (forks included, since a
      # fork's pull_request workflow run still carries THIS repo's sub) gets
      # this same claim.
      values = ["${var.github_oidc_sub_prefix}:pull_request"]
    }
  }
}

resource "aws_iam_role" "gha_deploy" {
  name               = "tricklens-gha-deploy"
  assume_role_policy = data.aws_iam_policy_document.gha_deploy_assume.json
}

resource "aws_iam_role" "gha_plan" {
  name               = "tricklens-gha-plan"
  assume_role_policy = data.aws_iam_policy_document.gha_plan_assume.json
}

# The deploy role is intentionally broad (close to PowerUserAccess) because
# `terraform apply` creates/mutates every resource in this directory. Scoped
# by name/ARN prefix everywhere the AWS API supports resource-level
# conditions; explicitly denied the handful of actions that would let it
# mint a persistent credential if ever misused.
data "aws_iam_policy_document" "gha_deploy_policy" {
  statement {
    sid = "BroadManage"
    actions = [
      "ecr:*",
      "lambda:*",
      "apigateway:*",
      "cloudfront:*",
      "s3:*",
      "sqs:*",
      "cognito-idp:*",
      "events:*",
      "budgets:*",
      "logs:*",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:PassRole",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:GetRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:TagRole",
      "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:GetOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
      "ssm:PutParameter",
      "ssm:GetParameter",
      "ssm:DeleteParameter",
      "ssm:AddTagsToResource",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "DenyPersistentCredentialCreation"
    effect    = "Deny"
    actions   = ["iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile", "organizations:*"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "gha_deploy" {
  name   = "tricklens-gha-deploy"
  role   = aws_iam_role.gha_deploy.id
  policy = data.aws_iam_policy_document.gha_deploy_policy.json
}

# Read-only: enough for `terraform plan` to diff every resource type above
# without being able to mutate anything, and no iam:PassRole (so it can't
# even stage a role-assumption for later).
data "aws_iam_policy_document" "gha_plan_policy" {
  statement {
    actions = [
      "ecr:Describe*", "ecr:List*", "ecr:GetLifecyclePolicy",
      "lambda:Get*", "lambda:List*",
      "apigateway:GET",
      "cloudfront:Get*", "cloudfront:List*",
      "s3:GetBucket*", "s3:GetObject*", "s3:ListBucket", "s3:ListAllMyBuckets",
      "sqs:GetQueue*", "sqs:List*",
      "cognito-idp:Describe*", "cognito-idp:List*",
      "events:Describe*", "events:List*",
      "budgets:View*", "budgets:Describe*",
      "logs:Describe*", "logs:List*", "logs:Get*",
      "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
      "iam:GetOpenIDConnectProvider",
      "ssm:DescribeParameters", "ssm:GetParameter",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "gha_plan" {
  name   = "tricklens-gha-plan"
  role   = aws_iam_role.gha_plan.id
  policy = data.aws_iam_policy_document.gha_plan_policy.json
}
