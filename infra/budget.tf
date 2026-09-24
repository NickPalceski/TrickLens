# docs/ARCHITECTURE.md's Cost section: ~$0.60/mo expected. $5 is the tripwire
# for "something went wrong" — the actual safety net for this stack's broad
# CI deploy role, not IAM scoping (see infra/iam.tf).
resource "aws_budgets_budget" "monthly" {
  name         = "tricklens-monthly"
  budget_type  = "COST"
  limit_amount = "5"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
