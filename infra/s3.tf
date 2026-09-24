locals {
  # Bucket names are globally unique across all AWS accounts, unlike the dev
  # LocalStack bucket ("tricklens-media") which only has to be unique inside
  # one docker network — suffix with the account id to avoid a collision.
  media_bucket_name = "tricklens-media-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "media" {
  bucket = local.media_bucket_name
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id

  block_public_acls       = true
  block_public_policy     = false # the bucket policy below is itself a public-ish grant, scoped to CloudFront only
  ignore_public_acls      = true
  restrict_public_buckets = false
}

# Mirrors scripts/localstack-init.sh's dev lifecycle rule: raw/ is
# pre-publish scratch space, never worth keeping past a week.
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "expire-raw-drafts"
    status = "Enabled"
    filter { prefix = "raw/" }
    expiration { days = 7 }
  }
}

resource "aws_cloudfront_origin_access_control" "media" {
  name                              = "tricklens-media-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Only CloudFront (via OAC, scoped to this specific distribution) may read
# the bucket — never public, never any other principal.
data "aws_iam_policy_document" "media_cloudfront_only" {
  statement {
    sid       = "AllowCloudFrontServicePrincipalReadOnly"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.media.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.media.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "media" {
  bucket = aws_s3_bucket.media.id
  policy = data.aws_iam_policy_document.media_cloudfront_only.json
}
