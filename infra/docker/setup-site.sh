#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# setup-site.sh — Creates and configures the ERPNext site after docker-compose is up
# Also configures Cognito SSO Social Login Key if Cognito env vars are present
set -euo pipefail

cd /opt/erpnext

# Source environment variables
source .env

SITE_NAME="${ERPNEXT_SITE_NAME:-p2p-erp.localhost}"

echo "=== Creating ERPNext site: ${SITE_NAME} ==="

# Wait for backend to be ready
echo "Waiting for backend container to be ready..."
for i in $(seq 1 30); do
    if docker compose exec -T backend bench --version 2>/dev/null; then
        echo "Backend is ready."
        break
    fi
    echo "  Attempt $i/30 — waiting 10s..."
    sleep 10
done

# Create the site with ERPNext app installed
echo "Creating site and installing ERPNext..."
docker compose exec -T backend bench new-site "${SITE_NAME}" \
    --mariadb-root-password "${DB_ROOT_PASSWORD}" \
    --admin-password "${ERPNEXT_ADMIN_PASSWORD}" \
    --install-app erpnext \
    --no-mariadb-socket \
    || echo "Site may already exist, continuing..."

# Set as default site
docker compose exec -T backend bench --site "${SITE_NAME}" set-config host_name "http://${SITE_NAME}"
docker compose exec -T backend bench use "${SITE_NAME}"

# Enable developer mode for API access and customization
docker compose exec -T backend bench --site "${SITE_NAME}" set-config developer_mode 1
docker compose exec -T backend bench --site "${SITE_NAME}" set-config allow_cors "*"

# Generate API keys for Administrator (used by data loading scripts and agents)
echo "Setting up API access..."
docker compose exec -T backend bench --site "${SITE_NAME}" execute frappe.core.doctype.user.user.generate_keys --args '["Administrator"]' \
    || echo "API keys may already exist"

# Enable REST API and clear cache
docker compose exec -T backend bench --site "${SITE_NAME}" clear-cache

# =====================================================================
# Cognito SSO Integration — Social Login Key
# =====================================================================
if [ -n "${COGNITO_DOMAIN:-}" ] && [ -n "${COGNITO_SSO_CLIENT_ID:-}" ]; then
    echo ""
    echo "=== Configuring Cognito SSO Integration ==="

    # Get the public IP for callback URL via IMDSv2 (token-protected)
    IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)
    if [ -n "${IMDS_TOKEN}" ]; then
        PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
            http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "localhost")
    else
        PUBLIC_IP="localhost"
    fi
    CALLBACK_URL="http://${PUBLIC_IP}:${ERPNEXT_PORT:-8080}/api/method/frappe.integrations.oauth2_logins.custom/cognito"

    # Configure Cognito as Social Login provider via bench console
    docker compose exec -T backend bench --site "${SITE_NAME}" execute frappe.client.insert --kwargs "$(cat <<PYEOF
{
    "doc": {
        "doctype": "Social Login Key",
        "name": "cognito",
        "enable_social_login": 1,
        "social_login_provider": "Custom",
        "provider_name": "AWS Cognito",
        "client_id": "${COGNITO_SSO_CLIENT_ID}",
        "custom_base_url": 1,
        "base_url": "${COGNITO_DOMAIN}",
        "authorize_url": "/oauth2/authorize",
        "access_token_url": "/oauth2/token",
        "redirect_url": "/api/method/frappe.integrations.oauth2_logins.custom/cognito",
        "api_endpoint": "${COGNITO_DOMAIN}/oauth2/userInfo",
        "auth_url_data": "{\"response_type\": \"code\", \"scope\": \"openid profile email\"}",
        "user_id_property": "email",
        "icon": "fa fa-lock"
    }
}
PYEOF
)" \
    || echo "Social Login Key 'cognito' may already exist or requires manual setup"

    echo ""
    echo "Cognito SSO configured."
    echo "  Callback URL: ${CALLBACK_URL}"
    echo ""
    echo "IMPORTANT: After deploy, update the Cognito App Client callback URL to:"
    echo "  ${CALLBACK_URL}"
    echo ""
    echo "  aws cognito-idp update-user-pool-client \\"
    echo "    --user-pool-id ${COGNITO_USER_POOL_ID:-<pool-id>} \\"
    echo "    --client-id ${COGNITO_SSO_CLIENT_ID} \\"
    echo "    --callback-urls '${CALLBACK_URL}' \\"
    echo "    --allowed-o-auth-flows code \\"
    echo "    --allowed-o-auth-scopes openid email profile \\"
    echo "    --supported-identity-providers COGNITO"
    echo ""
    echo "Then also set the client_secret in ERPNext Social Login Key:"
    echo "  1. Get the secret: aws cognito-idp describe-user-pool-client --user-pool-id ${COGNITO_USER_POOL_ID:-<pool-id>} --client-id ${COGNITO_SSO_CLIENT_ID}"
    echo "  2. In ERPNext: Setup > Integrations > Social Login Key > cognito > set Client Secret"
else
    echo ""
    echo "[INFO] Cognito env vars not set — skipping SSO configuration."
    echo "  To enable Cognito SSO later, set COGNITO_DOMAIN and COGNITO_SSO_CLIENT_ID in .env"
fi

echo ""
echo "=== ERPNext Site Setup Complete ==="
echo "Site: ${SITE_NAME}"
echo "URL:  http://<your-ec2-ip>:${ERPNEXT_PORT:-8080}"
echo "Login: Administrator / ${ERPNEXT_ADMIN_PASSWORD}"
echo ""
echo "Authentication methods available:"
echo "  1. Local login: Administrator / password"
echo "  2. API token:   Authorization: token api_key:api_secret"
if [ -n "${COGNITO_DOMAIN:-}" ]; then
    echo "  3. Cognito SSO: Click 'Login with AWS Cognito' on login page"
    echo "  4. M2M (Agent): client_credentials grant from Cognito -> ERPNext API"
fi
