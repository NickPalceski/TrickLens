resource "aws_cloudfront_distribution" "media" {
  enabled     = true
  comment     = "tricklens media"
  price_class = "PriceClass_100" # US/Canada/Europe only — cheapest tier, plenty for a hobby project
  # media.tricklens.com (F4, infra/domain.tf). The default *.cloudfront.net
  # name keeps working too, so clip URLs built before the switch still load.
  aliases         = [local.media_domain]
  is_ipv6_enabled = true

  origin {
    domain_name              = aws_s3_bucket.media.bucket_regional_domain_name
    origin_id                = "media-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  default_cache_behavior {
    target_origin_id       = "media-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 86400
    max_ttl     = 604800
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
