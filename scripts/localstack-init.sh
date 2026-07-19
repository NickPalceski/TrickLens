#!/bin/bash
# Runs automatically when LocalStack becomes ready (mounted into
# /etc/localstack/init/ready.d/). Creates the same resources that Terraform
# will create in AWS for real, so local and cloud have identical shapes.
set -euo pipefail

BUCKET="tricklens-media"
QUEUE="tricklens-analysis"
DLQ="tricklens-analysis-dlq"

echo "[init] creating S3 bucket: ${BUCKET}"
awslocal s3api create-bucket --bucket "${BUCKET}"

# The browser uploads straight to S3 from a different origin, so the bucket
# needs CORS. Real AWS needs this too — it is a common first-deploy gotcha.
echo "[init] applying bucket CORS"
awslocal s3api put-bucket-cors --bucket "${BUCKET}" --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["http://localhost:3000"],
      "AllowedMethods": ["GET", "PUT", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }
  ]
}'

# Drafts that are never published would otherwise accumulate forever.
# Mirrors the lifecycle rule Terraform will create in production.
echo "[init] applying lifecycle rule (expire raw/ after 7 days)"
awslocal s3api put-bucket-lifecycle-configuration --bucket "${BUCKET}" --lifecycle-configuration '{
  "Rules": [
    {
      "ID": "expire-unpublished-drafts",
      "Status": "Enabled",
      "Filter": { "Prefix": "raw/" },
      "Expiration": { "Days": 7 }
    }
  ]
}'

# Dead-letter queue first, so the main queue can reference it.
echo "[init] creating SQS queue: ${DLQ}"
awslocal sqs create-queue --queue-name "${DLQ}"
DLQ_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url "http://localhost:4566/000000000000/${DLQ}" \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' --output text)

# VisibilityTimeout must exceed the worker's max runtime, or a slow clip gets
# picked up twice. 90s of analysis -> 300s here, with headroom.
echo "[init] creating SQS queue: ${QUEUE} (maxReceiveCount=3 -> DLQ)"
awslocal sqs create-queue --queue-name "${QUEUE}" --attributes "{
  \"VisibilityTimeout\": \"300\",
  \"MessageRetentionPeriod\": \"345600\",
  \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"${DLQ_ARN}\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"
}"

echo "[init] done"
