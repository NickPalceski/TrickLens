output "api_invoke_url" {
  value = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
}

output "ecr_repo_url" {
  value = aws_ecr_repository.main.repository_url
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.media.domain_name
}

output "cdn_base_url" {
  value = "https://${aws_cloudfront_distribution.media.domain_name}"
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.prod.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "sqs_queue_url" {
  value = aws_sqs_queue.analysis.url
}

output "s3_bucket_name" {
  value = aws_s3_bucket.media.bucket
}

output "github_oidc_deploy_role_arn" {
  value = aws_iam_role.gha_deploy.arn
}

output "github_oidc_plan_role_arn" {
  value = aws_iam_role.gha_plan.arn
}
