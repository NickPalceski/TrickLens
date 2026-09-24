#!/bin/bash
# One-time, hand-run setup for the Terraform state backend (S3 + DynamoDB
# lock table) — same idiom as scripts/cognito-bootstrap.sh: idempotent,
# never wired into anything automatic, only touches AWS when a person runs
# it on purpose.
#
# This bucket/table are deliberately NEVER managed by infra/*.tf — a backend
# can't safely manage the store it's sitting in. See infra/backend.tf.
#
# Prereqs: an AWS account with `aws configure` already pointing at it (the
# same one Cognito's dev pool lives in — see README's Auth setup).
#
# Usage: ./scripts/terraform-bootstrap.sh
# Then: terraform -chdir=infra init \
#         -backend-config="bucket=$(that script's printed bucket name)" \
#         -backend-config="dynamodb_table=tricklens-terraform-locks" \
#         -backend-config="region=us-east-1" \
#         -backend-config="key=prod/terraform.tfstate"
# (`make tf-init` does exactly this — see the Makefile.)
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="tricklens-terraform-state-${ACCOUNT_ID}"
TABLE="tricklens-terraform-locks"

echo "[terraform-bootstrap] looking for an existing state bucket '${BUCKET}'..."
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "[terraform-bootstrap] found existing bucket — reusing it."
else
  echo "[terraform-bootstrap] creating state bucket: ${BUCKET}"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  aws s3api put-bucket-versioning --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

echo "[terraform-bootstrap] looking for an existing lock table '${TABLE}'..."
if aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "[terraform-bootstrap] found existing table — reusing it."
else
  echo "[terraform-bootstrap] creating lock table: ${TABLE}"
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
fi

cat <<EOF

[terraform-bootstrap] done.

  State bucket: ${BUCKET}
  Lock table:   ${TABLE}

Both are deterministic (same AWS account -> same bucket name via the account
id suffix), so this never needs to be shared between machines by hand — run
this script once per machine before that machine's first 'make tf-init'.

Next: 'make tf-init' (or see the -backend-config flags in this script's
header) to point Terraform at this backend, then read README's Deployment
section for the rest of the first-ever-deploy sequence.

EOF
