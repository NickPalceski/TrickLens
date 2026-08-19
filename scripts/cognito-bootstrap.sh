#!/bin/bash
# One-time, hand-run setup for the dev Cognito user pool.
#
# Unlike scripts/localstack-init.sh, this is NOT wired into
# `docker compose up` and must never be. It touches a real AWS account, so it
# only runs when a person runs it on purpose.
#
# Prereqs: an AWS account, an IAM user with Cognito permissions, and
# `aws configure` already pointing the CLI at it. See README's setup section.
#
# Usage: ./scripts/cognito-bootstrap.sh
# Then paste the printed IDs into .env.
set -euo pipefail

POOL_NAME="tricklens-dev"
CLIENT_NAME="tricklens-web"
REGION="${AWS_REGION:-us-east-1}"

echo "[cognito-bootstrap] looking for an existing pool named '${POOL_NAME}'..."
EXISTING_POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --region "$REGION" \
  --query "UserPools[?Name=='${POOL_NAME}'].Id | [0]" --output text)

if [ "$EXISTING_POOL_ID" != "None" ] && [ -n "$EXISTING_POOL_ID" ]; then
  echo "[cognito-bootstrap] found existing pool: ${EXISTING_POOL_ID} — reusing it."
  POOL_ID="$EXISTING_POOL_ID"
else
  echo "[cognito-bootstrap] creating user pool: ${POOL_NAME}"
  # Sign in with email, not a separate "Cognito username" — the app already
  # has its own username field (the public handle), and two namespaces for
  # the same idea would just be confusing.
  POOL_ID=$(aws cognito-idp create-user-pool \
    --pool-name "$POOL_NAME" \
    --auto-verified-attributes email \
    --username-attributes email \
    --region "$REGION" \
    --query 'UserPool.Id' --output text)
fi

echo "[cognito-bootstrap] looking for an existing app client named '${CLIENT_NAME}'..."
EXISTING_CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "$POOL_ID" --region "$REGION" \
  --query "UserPoolClients[?ClientName=='${CLIENT_NAME}'].ClientId | [0]" --output text)

if [ "$EXISTING_CLIENT_ID" != "None" ] && [ -n "$EXISTING_CLIENT_ID" ]; then
  echo "[cognito-bootstrap] found existing app client: ${EXISTING_CLIENT_ID} — reusing it."
  CLIENT_ID="$EXISTING_CLIENT_ID"
else
  echo "[cognito-bootstrap] creating app client: ${CLIENT_NAME}"
  # No secret: this is the same public client a browser will eventually call
  # directly. USER_PASSWORD_AUTH is enabled so it's curl-testable before a
  # frontend exists; a real frontend (step 4) should move to SRP instead.
  CLIENT_ID=$(aws cognito-idp create-user-pool-client \
    --user-pool-id "$POOL_ID" \
    --client-name "$CLIENT_NAME" \
    --no-generate-secret \
    --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
    --region "$REGION" \
    --query 'UserPoolClient.ClientId' --output text)
fi

cat <<EOF

[cognito-bootstrap] done. Add these to .env:

  COGNITO_USER_POOL_ID=${POOL_ID}
  COGNITO_CLIENT_ID=${CLIENT_ID}

EOF
