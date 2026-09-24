locals {
  image_uri = "${aws_ecr_repository.main.repository_url}:${var.image_tag}"

  # One shared env for all three functions: app.config.Settings requires
  # s3_bucket/sqs_analysis_queue_url/cdn_base_url/etc. unconditionally
  # (no defaults), so even the worker and rankings Lambdas — which never
  # functionally use most of these — still need them present just to let
  # Settings() construct successfully. Same idiom as local dev, where one
  # .env serves uvicorn, the poll loop, and `make rankings` alike.
  lambda_env = {
    ENV                    = "prod"
    S3_BUCKET              = aws_s3_bucket.media.bucket
    SQS_ANALYSIS_QUEUE_URL = aws_sqs_queue.analysis.url
    CDN_BASE_URL           = "https://${aws_cloudfront_distribution.media.domain_name}"
    CORS_ORIGINS           = var.cors_origins
    COGNITO_USER_POOL_ID   = aws_cognito_user_pool.prod.id
    COGNITO_CLIENT_ID      = aws_cognito_user_pool_client.web.id
    DATABASE_URL_SSM_PARAM = aws_ssm_parameter.database_url.name
    # AWS_ENDPOINT_URL / AWS_PUBLIC_ENDPOINT_URL / AWS_ACCESS_KEY_ID /
    # AWS_SECRET_ACCESS_KEY are deliberately absent — see docs/ARCHITECTURE.md
    # §9 and app/config.py's Settings defaults.
  }
}

resource "aws_lambda_function" "api" {
  function_name = "tricklens-api"
  role          = aws_iam_role.api_lambda.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  image_config {
    command = ["app.lambda_handler.handler"]
  }
  timeout     = 29 # matches API Gateway's hard request cap
  memory_size = 512

  environment {
    variables = local.lambda_env
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

resource "aws_lambda_function" "worker" {
  function_name = "tricklens-worker"
  role          = aws_iam_role.worker_lambda.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  image_config {
    command = ["app.worker.lambda_handler"]
  }
  timeout     = 90
  memory_size = 512

  environment {
    variables = local.lambda_env
  }

  depends_on = [aws_cloudwatch_log_group.worker]
}

resource "aws_lambda_function" "rankings" {
  function_name = "tricklens-rankings"
  role          = aws_iam_role.rankings_lambda.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  image_config {
    command = ["app.rankings.lambda_handler"]
  }
  timeout     = 60
  memory_size = 256

  environment {
    variables = local.lambda_env
  }

  depends_on = [aws_cloudwatch_log_group.rankings]
}
