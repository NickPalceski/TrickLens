# HTTP API, not REST API — cheaper, and Mangum (app/lambda_handler.py)
# already speaks the v2 proxy payload format natively.
resource "aws_apigatewayv2_api" "main" {
  name          = "tricklens-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

# POST /bug-reports works signed out (docs/components/frontend.md, Reports),
# so it gets its own route, only so the stage can throttle it on its own.
# Same integration as $default; every other request still goes there.
resource "aws_apigatewayv2_route" "bug_reports" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /bug-reports"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # A backstop against someone filling the reports table, not a per-person
  # limit: API Gateway throttles the route as a whole, across all callers.
  # Far above what real bug reports need.
  route_settings {
    route_key              = aws_apigatewayv2_route.bug_reports.route_key
    throttling_burst_limit = 5
    throttling_rate_limit  = 1
  }
}

# api.tricklens.com (F4, infra/domain.tf). The execute-api URL keeps
# working; the deploy's smoke test still uses it.
resource "aws_apigatewayv2_domain_name" "api" {
  domain_name = local.api_domain

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.main.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "api" {
  api_id      = aws_apigatewayv2_api.main.id
  domain_name = aws_apigatewayv2_domain_name.api.id
  stage       = aws_apigatewayv2_stage.default.id
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"

  lifecycle {
    replace_triggered_by = [aws_lambda_function.api]
  }
}
