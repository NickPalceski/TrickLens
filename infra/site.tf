# The web app (frontend/apps/web) as static files: a private S3 bucket
# behind its own CloudFront distribution at tricklens.com (F4). Separate
# from the media bucket and CDN so a site deploy can never touch clips, and
# so each keeps its own cache rules. Filled by the deploy (docs/deployment.md);
# until the first upload the site answers with an error page.

resource "aws_s3_bucket" "site" {
  bucket = "tricklens-site-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = false # the policy below grants CloudFront only, same as the media bucket
  ignore_public_acls      = true
  restrict_public_buckets = false
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "tricklens-site-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "site_cloudfront_only" {
  statement {
    sid       = "AllowCloudFrontServicePrincipalReadOnly"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_cloudfront_only.json
}

# www.tricklens.com → tricklens.com, so the app has one origin: one place
# for saved passwords and the stored sign-in, and one CORS origin.
resource "aws_cloudfront_function" "www_redirect" {
  name    = "tricklens-www-redirect"
  runtime = "cloudfront-js-2.0"
  comment = "Redirect www.${var.domain_name} to the apex"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      if (request.headers.host && request.headers.host.value === '${local.www_domain}') {
        return {
          statusCode: 301,
          statusDescription: 'Moved Permanently',
          headers: { location: { value: '${local.site_origin}' + request.uri } },
        };
      }
      return request;
    }
  EOT
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "tricklens web app"
  price_class         = "PriceClass_100"
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = [local.site_domain, local.www_domain]

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "site-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id           = "site-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.www_redirect.arn
    }
  }

  # A single-page app: /feed, /clips/<id> and every other route is
  # index.html, and the browser's router takes it from there. S3 answers a
  # missing key with 403 when CloudFront can't list the bucket, so both map.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.main.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
