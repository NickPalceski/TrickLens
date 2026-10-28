# tricklens.com (F4). Registered through Route 53 by hand (2026-10-27),
# which created its hosted zone. Terraform only looks the zone up, never
# manages it: the registration's nameservers point at that exact zone, and
# recreating it would hand out new nameservers and take the domain offline.
# See docs/components/infrastructure.md, The domain.

data "aws_route53_zone" "main" {
  name         = var.domain_name
  private_zone = false
}

locals {
  site_domain  = var.domain_name            # the web app
  www_domain   = "www.${var.domain_name}"   # redirects to the apex
  api_domain   = "api.${var.domain_name}"   # API Gateway custom domain
  media_domain = "media.${var.domain_name}" # the media CloudFront
  site_origin  = "https://${var.domain_name}"
}

# One certificate for every name. It must be in us-east-1 for CloudFront,
# and a regional API Gateway domain needs it in the API's own region, which
# is the same one here (var.aws_region defaults to us-east-1).
resource "aws_acm_certificate" "main" {
  domain_name               = local.site_domain
  subject_alternative_names = [local.www_domain, local.api_domain, local.media_domain]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# ACM proves we own the names by asking for these CNAMEs, then renews the
# certificate by itself for as long as they stay.
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for o in aws_acm_certificate.main.domain_validation_options : o.domain_name => {
      name   = o.resource_record_name
      type   = o.resource_record_type
      record = o.resource_record_value
    }
  }

  zone_id         = data.aws_route53_zone.main.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 300
  allow_overwrite = true
}

# Waits (usually a few minutes) until ACM has seen the records and issued
# the certificate, so nothing below tries to use it before then.
resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# --- Records: every name is an alias to its AWS target ----------------------

resource "aws_route53_record" "site" {
  for_each = toset(["A", "AAAA"])

  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.site_domain
  type    = each.key
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "www" {
  for_each = toset(["A", "AAAA"])

  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.www_domain
  type    = each.key
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "media" {
  for_each = toset(["A", "AAAA"])

  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.media_domain
  type    = each.key
  alias {
    name                   = aws_cloudfront_distribution.media.domain_name
    zone_id                = aws_cloudfront_distribution.media.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.api_domain
  type    = "A"
  alias {
    name                   = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
