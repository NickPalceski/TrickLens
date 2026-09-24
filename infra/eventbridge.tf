# Discover is a precomputed snapshot (docs/ARCHITECTURE.md §7) — this is
# what rebuilds it in production, replacing `make rankings` run on demand.
resource "aws_cloudwatch_event_rule" "rankings_schedule" {
  name                = "tricklens-rankings-schedule"
  schedule_expression = var.rankings_schedule_expression
}

resource "aws_cloudwatch_event_target" "rankings" {
  rule = aws_cloudwatch_event_rule.rankings_schedule.name
  arn  = aws_lambda_function.rankings.arn
}

resource "aws_lambda_permission" "eventbridge_rankings" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rankings.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rankings_schedule.arn
}
