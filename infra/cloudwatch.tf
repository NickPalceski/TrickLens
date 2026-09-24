# Pre-created so Lambda uses these (with a real retention policy) instead of
# auto-creating its own never-expiring log group on first invoke — avoids
# unbounded CloudWatch Logs storage cost creep.
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/tricklens-api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/tricklens-worker"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "rankings" {
  name              = "/aws/lambda/tricklens-rankings"
  retention_in_days = 14
}
