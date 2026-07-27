# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Set up ERPNext as an OAuth2 provider for the P2P agentic platform.

ERPNext supports OAuth2 natively via Frappe's oauth2 module:
- Authorization endpoint: /api/method/frappe.integrations.oauth2.authorize
- Token endpoint: /api/method/frappe.integrations.oauth2.get_token
- Userinfo: /api/method/frappe.integrations.oauth2.openid_profile

This script:
1. Creates an OAuth Client in ERPNext
2. Generates API key pairs for each demo user (simpler than full OAuth for demo)
3. Stores all credentials in AWS Secrets Manager
"""

import json
import sys
import os

import boto3
import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import ERPNEXT_URL, ERPNEXT_USER, ERPNEXT_PASSWORD

PREFIX = os.getenv("STACK_PREFIX", "p2p-dev")
REGION = os.getenv("AWS_REGION", "us-east-1")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "https://localhost/callback")

# All users that need API keys (demo + simulation + service)
# Imported from 02_setup_users.py for single source of truth
try:
    from utilities.scripts import DEMO_PERSONAS, SIMULATION_USERS, SERVICE_USERS
    ALL_API_USERS = [u["email"] for u in DEMO_PERSONAS + SIMULATION_USERS + SERVICE_USERS]
except ImportError:
    ALL_API_USERS = [
        "demo+maria@example.com",
        "demo+sarah@example.com",
        "demo+jake@example.com",
        "demo+priya@example.com",
        "demo+gary@example.com",
        "demo+carlos@example.com",
        "demo+aisha@example.com",
        "demo+wei@example.com",
        "demo+tom@example.com",
        "demo+lisa@example.com",
        "demo+carlos_r@example.com",
        "demo+aisha_k@example.com",
        "demo+dave@example.com",
        "demo+yuki@example.com",
        "demo+rachel@example.com",
        "demo+agent@example.com",
    ]


def get_session() -> requests.Session:
    """Authenticate to ERPNext and return session."""
    s = requests.Session()
    # nosemgrep -- use-timeout: demo/setup script; long-running ERPNext calls are expected
    resp = s.post(
        f"{ERPNEXT_URL}/api/method/login",
        data={"usr": ERPNEXT_USER, "pwd": ERPNEXT_PASSWORD},
    )
    resp.raise_for_status()
    print(f"Authenticated to {ERPNEXT_URL}")
    return s


def create_oauth_client(session: requests.Session) -> dict:
    """Create an OAuth Client in ERPNext (or return existing)."""
    client_name = "P2P Agentic Platform"

    # Check if already exists
    resp = session.get(
        f"{ERPNEXT_URL}/api/resource/OAuth Client",
        params={"filters": json.dumps([["app_name", "=", client_name]])},
    )
    existing = resp.json().get("data", [])
    if existing:
        doc = session.get(
            f"{ERPNEXT_URL}/api/resource/OAuth Client/{existing[0]['name']}"
        ).json()["data"]
        print(f"OAuth Client already exists: {doc['name']}")
        return {"client_id": doc["client_id"], "client_secret": doc.get("client_secret", "")}

    # Create new
    resp = session.post(
        f"{ERPNEXT_URL}/api/resource/OAuth Client",
        json={
            "data": json.dumps({
                "doctype": "OAuth Client",
                "app_name": client_name,
                "scopes": "all openid",
                "redirect_urls": REDIRECT_URI,
                "default_redirect_uri": REDIRECT_URI,
                "grant_type": "Authorization Code",
                "response_type": "Code",
            })
        },
    )
    resp.raise_for_status()
    doc = resp.json()["data"]
    print(f"Created OAuth Client: {doc['name']}")
    return {"client_id": doc["client_id"], "client_secret": doc.get("client_secret", "")}


def generate_api_keys(session: requests.Session, email: str) -> dict:
    """Generate API key + secret for an ERPNext user."""
    resp = session.post(
        f"{ERPNEXT_URL}/api/method/frappe.core.doctype.user.user.generate_keys",
        data={"user": email},
    )
    if resp.status_code != 200:
        print(f"  [WARN] Could not generate keys for {email}: {resp.text[:100]}")
        return {}
    data = resp.json()
    api_secret = data.get("message", {}).get("api_secret", "")
    # Fetch the api_key from user doc
    user_doc = session.get(f"{ERPNEXT_URL}/api/resource/User/{email}").json()["data"]
    api_key = user_doc.get("api_key", "")
    print(f"  Generated API keys for {email}")
    return {"api_key": api_key, "api_secret": api_secret}


def store_in_secrets_manager(oauth: dict, user_keys: dict):
    """Store all credentials in AWS Secrets Manager."""
    sm = boto3.client("secretsmanager", region_name=REGION)
    secret_name = f"{PREFIX}/erpnext-credentials"

    secret_value = {
        "url": ERPNEXT_URL,
        "oauth_client_id": oauth.get("client_id", ""),
        "oauth_client_secret": oauth.get("client_secret", ""),
        "service_api_key": user_keys.get("demo+agent@example.com", {}).get("api_key", ""),
        "service_api_secret": user_keys.get("demo+agent@example.com", {}).get("api_secret", ""),
        "user_keys": user_keys,
    }

    try:
        sm.put_secret_value(SecretId=secret_name, SecretString=json.dumps(secret_value))
        print(f"\nUpdated secret: {secret_name}")
    except sm.exceptions.ResourceNotFoundException:
        sm.create_secret(Name=secret_name, SecretString=json.dumps(secret_value))
        print(f"\nCreated secret: {secret_name}")


def get_cdk_outputs() -> dict:
    """Read CDK stack outputs for Cognito SSO configuration."""
    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        resp = cf.describe_stacks(StackName=f"{PREFIX.replace('-dev', '').capitalize()}AgenticStack")
        outputs = {}
        for o in resp["Stacks"][0].get("Outputs", []):
            outputs[o["OutputKey"]] = o["OutputValue"]
        return outputs
    except Exception:
        # Try with the exact stack name
        try:
            cf = boto3.client("cloudformation", region_name=REGION)
            resp = cf.describe_stacks(StackName="P2PAgenticStack")
            return {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
        except Exception as e:
            print(f"  [WARN] Could not read CDK outputs: {e}")
            return {}


def get_cognito_client_secret(pool_id: str, client_id: str) -> str:
    """Get the client secret for the ERPNext SSO Cognito app client."""
    try:
        cognito = boto3.client("cognito-idp", region_name=REGION)
        resp = cognito.describe_user_pool_client(
            UserPoolId=pool_id,
            ClientId=client_id,
        )
        return resp["UserPoolClient"].get("ClientSecret", "")
    except Exception as e:
        print(f"  [WARN] Could not get Cognito client secret: {e}")
        return ""


def configure_cognito_sso(session: requests.Session):
    """Configure Cognito as a Social Login provider in ERPNext.

    Reads CDK outputs for Cognito domain, SSO client ID, and client secret,
    then creates/updates the Social Login Key in ERPNext.

    See docs/ERPNEXT_COGNITO_SSO.md for manual setup if this fails.
    """
    print("\n🔗 Configuring Cognito SSO in ERPNext...")

    outputs = get_cdk_outputs()
    pool_id = outputs.get("CognitoUserPoolId", "")
    sso_client_id = outputs.get("ERPNextSSOClientId", "")
    cognito_domain = outputs.get("CognitoDomain", "")

    if not pool_id or not sso_client_id or not cognito_domain:
        print("  [SKIP] Missing CDK outputs (CognitoUserPoolId, ERPNextSSOClientId, CognitoDomain)")
        print("         Deploy P2PAgenticStack first, or configure SSO manually.")
        print("         See: docs/ERPNEXT_COGNITO_SSO.md")
        return

    client_secret = get_cognito_client_secret(pool_id, sso_client_id)
    if not client_secret:
        print("  [SKIP] Could not retrieve Cognito client secret")
        return

    base_url = f"https://{cognito_domain}.auth.{REGION}.amazoncognito.com"
    redirect_url = f"{ERPNEXT_URL}/api/method/frappe.integrations.oauth2_logins.custom/amazon_cognito"
    provider_name = "Amazon Cognito"

    # Check if Social Login Key already exists
    resp = session.get(
        f"{ERPNEXT_URL}/api/resource/Social Login Key",
        params={"filters": json.dumps([["provider_name", "=", provider_name]])},
    )
    existing = resp.json().get("data", []) if resp.status_code == 200 else []

    doc = {
        "doctype": "Social Login Key",
        "enable_social_login": 1,
        "social_login_provider": "Custom",
        "provider_name": provider_name,
        "client_id": sso_client_id,
        "client_secret": client_secret,
        "base_url": base_url,
        "authorize_url": "/oauth2/authorize",
        "access_token_url": "/oauth2/token",
        "redirect_url": redirect_url,
        "api_endpoint": f"{base_url}/oauth2/userInfo",
        "auth_url_data": json.dumps({"scope": "openid email profile", "response_type": "code"}),
        "user_id_property": "email",
    }

    if existing:
        # Update existing
        name = existing[0]["name"]
        resp = session.put(
            f"{ERPNEXT_URL}/api/resource/Social Login Key/{name}",
            json={"data": json.dumps(doc)},
        )
        if resp.status_code == 200:
            print(f"  [OK]   Updated Social Login Key: {provider_name}")
        else:
            print(f"  [WARN] Failed to update Social Login Key: {resp.status_code} {resp.text[:200]}")
    else:
        # Create new
        resp = session.post(
            f"{ERPNEXT_URL}/api/resource/Social Login Key",
            json={"data": json.dumps(doc)},
        )
        if resp.status_code == 200:
            print(f"  [OK]   Created Social Login Key: {provider_name}")
        else:
            print(f"  [WARN] Failed to create Social Login Key: {resp.status_code} {resp.text[:200]}")
            print("         Configure SSO manually — see docs/ERPNEXT_COGNITO_SSO.md")

    print(f"  Base URL:     {base_url}")
    print(f"  Redirect URL: {redirect_url}")


def main():
    session = get_session()

    # 1. Create OAuth Client
    oauth = create_oauth_client(session)
    print(f"OAuth client_id: {oauth['client_id']}")

    # 2. Generate API keys for ALL users (demo + simulation + service)
    user_keys = {}
    for email in ALL_API_USERS:
        keys = generate_api_keys(session, email)
        if keys:
            user_keys[email] = keys

    # 3. Store in Secrets Manager
    store_in_secrets_manager(oauth, user_keys)

    # 4. Configure Cognito SSO in ERPNext (optional — needs CDK deployed)
    configure_cognito_sso(session)

    print("\n✅ ERPNext OAuth setup complete")
    print(f"   OAuth endpoints:")
    print(f"   - Authorize: {ERPNEXT_URL}/api/method/frappe.integrations.oauth2.authorize")
    print(f"   - Token:     {ERPNEXT_URL}/api/method/frappe.integrations.oauth2.get_token")
    print(f"   SSO guide:   docs/ERPNEXT_COGNITO_SSO.md")


if __name__ == "__main__":
    main()
