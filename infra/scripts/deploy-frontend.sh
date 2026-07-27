#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# Deploy frontend: read CDK outputs → write .env.production → build → sync to S3
set -euo pipefail

# Use nvm node if available (avoids version mismatch with node_modules)
NVM_NODE="$HOME/.nvm/versions/node/v22.14.0/bin"
if [ -d "$NVM_NODE" ]; then
  export PATH="$NVM_NODE:$PATH"
fi

PROFILE="${AWS_PROFILE:-${1:-default}}"
STACK="P2PAgenticStack"
FRONTEND_DIR="$(cd "$(dirname "$0")/../../frontend" && pwd)"

echo "Reading stack outputs (profile: $PROFILE)..."
OUTPUTS=$(aws cloudformation describe-stacks --stack-name "$STACK" --profile "$PROFILE" --query 'Stacks[0].Outputs' --output json)

get() { echo "$OUTPUTS" | python3 -c "import json,sys; o=json.load(sys.stdin); print(next((x['OutputValue'] for x in o if x['OutputKey']=='$1'), ''))"; }

POOL_ID=$(get CognitoUserPoolId)
CLIENT_ID=$(get CognitoClientId)
IDENTITY_POOL=$(get CognitoIdentityPoolId)
BUCKET=$(get FrontendBucketName)
CF_URL=$(get CloudFrontUrl)

if [ -z "$POOL_ID" ] || [ -z "$BUCKET" ]; then
  echo "ERROR: Stack outputs missing. Deploy infra first: cdk deploy P2PAgenticStack"
  exit 1
fi

# VITE_DEMO_PASSWORD is OPTIONAL — when set, the Login page enables one-click
# quick-login for demo personas. Leave it unset to require manual login only.
# Set via env (e.g. export VITE_DEMO_PASSWORD='YourDemoPassword!') before
# running this script. Should match the password used in 02_setup_users.py.
DEMO_PWD="${VITE_DEMO_PASSWORD:-}"

# Write .env.production
cat > "$FRONTEND_DIR/.env.production" <<EOF
VITE_API_URL=/api
VITE_COGNITO_POOL_ID=$POOL_ID
VITE_COGNITO_CLIENT_ID=$CLIENT_ID
VITE_COGNITO_IDENTITY_POOL_ID=$IDENTITY_POOL
VITE_DEMO_PASSWORD=$DEMO_PWD
EOF

# Add AgentCore ARNs
for name in requisition sourcing po_management receiving invoice_matching payment workflow; do
  KEY="AgentCore${name}Arn"
  ARN=$(get "$KEY")
  if [ -n "$ARN" ]; then
    UPPER=$(echo "$name" | tr '[:lower:]' '[:upper:]')
    echo "VITE_AGENTCORE_${UPPER}_ARN=$ARN" >> "$FRONTEND_DIR/.env.production"
  fi
done

echo "Wrote $FRONTEND_DIR/.env.production"
cat "$FRONTEND_DIR/.env.production"

# Build
echo ""
echo "Building frontend..."
cd "$FRONTEND_DIR"
npm run build

# Sync to S3
echo ""
echo "Uploading to s3://$BUCKET..."
aws s3 sync dist/ "s3://$BUCKET/" --delete --profile "$PROFILE"

# Invalidate CloudFront
DIST_ID=$(aws cloudfront list-distributions --profile "$PROFILE" --query "DistributionList.Items[?Aliases.Items[0]!=null]|[0].Id" --output text 2>/dev/null || true)
if [ -n "$DIST_ID" ] && [ "$DIST_ID" != "None" ]; then
  echo "Invalidating CloudFront ($DIST_ID)..."
  aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" --profile "$PROFILE" --query 'Invalidation.Status' --output text
fi

echo ""
echo "Done! Frontend deployed to $CF_URL"
