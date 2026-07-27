#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Create users in BOTH ERPNext and Cognito for the P2P demo.

Single script — one persona definition drives both systems:
  - ERPNext: creates user accounts with ERP roles (Purchase User, Accounts User, etc.)
  - Cognito: creates user pool entries with app roles (requester, approver, ap_clerk, etc.)

Usage:
    python scripts/02_setup_users.py                     # Both systems
    python scripts/02_setup_users.py --erpnext-only       # ERPNext only
    python scripts/02_setup_users.py --cognito-only       # Cognito only
    python scripts/02_setup_users.py --delete-cognito     # Reset Cognito users first
    python scripts/02_setup_users.py --pool-id us-east-1_XXX  # Manual pool ID
"""

import argparse
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
from config import ERPNEXT_URL, ERPNEXT_USER, ERPNEXT_PASSWORD

DEFAULT_PASSWORD = os.getenv("ERPNEXT_USER_PASSWORD")
if not DEFAULT_PASSWORD:
    raise RuntimeError(
        "ERPNEXT_USER_PASSWORD is not set. Choose a strong password and export "
        "it (or set it in utilities/.env) before running this script. "
        "Example: export ERPNEXT_USER_PASSWORD='ChooseAStrongDemoPassword!'"
    )

# ══════════════════════════════════════════════════════════════════════════════
# PERSONA DEFINITIONS — single source of truth for both systems
# ══════════════════════════════════════════════════════════════════════════════

DEMO_PERSONAS = [
    {
        "email": "demo+maria@example.com",
        "first_name": "Maria", "last_name": "Chen",
        "cognito_username": "maria.chen",
        "cognito_role": "requester",
        "cognito_group": "requester",
        "department": "Manufacturing",
        "erpnext_roles": ["Purchase User", "Stock User", "Employee"],
        "description": "Factory Floor Supervisor — creates Material Requests via chat",
    },
    {
        "email": "demo+sarah@example.com",
        "first_name": "Sarah", "last_name": "Johnson",
        "cognito_username": "sarah.johnson",
        "cognito_role": "approver",
        "cognito_group": "approver",
        "department": "Procurement",
        "erpnext_roles": ["Purchase Manager", "Purchase User", "Stock User", "Employee"],
        "description": "Procurement Manager — reviews agent recommendations",
    },
    {
        "email": "demo+jake@example.com",
        "first_name": "Jake", "last_name": "Rodriguez",
        "cognito_username": "jake.rodriguez",
        "cognito_role": "procurement",
        "cognito_group": "procurement",
        "department": "Procurement",
        "erpnext_roles": ["Purchase Manager", "Purchase User", "Stock User", "Stock Manager", "Employee"],
        "description": "Buyer — manages POs and supplier relationships",
    },
    {
        "email": "demo+priya@example.com",
        "first_name": "Priya", "last_name": "Patel",
        "cognito_username": "priya.patel",
        "cognito_role": "ap_clerk",
        "cognito_group": "ap_clerk",
        "department": "Finance",
        "erpnext_roles": ["Accounts User", "Accounts Manager", "Purchase User", "Employee"],
        "description": "AP Clerk — reviews invoice matches and payments",
    },
    {
        "email": "demo+gary@example.com",
        "first_name": "Gary", "last_name": "Wilson",
        "cognito_username": "gary.wilson",
        "cognito_role": "executive",
        "cognito_group": "executive",
        "department": "Operations",
        "erpnext_roles": ["Analytics", "Purchase User", "Stock User", "Accounts User", "Employee"],
        "description": "VP Operations — dashboards and spend analytics",
    },
    {
        "email": "demo+carlos@example.com",
        "first_name": "Carlos", "last_name": "Mendez",
        "cognito_username": "carlos.mendez",
        "cognito_role": "requester",
        "cognito_group": "requester",
        "department": "Maintenance",
        "erpnext_roles": ["Purchase User", "Stock User", "Employee"],
        "description": "Maintenance Technician",
    },
    {
        "email": "demo+aisha@example.com",
        "first_name": "Aisha", "last_name": "Okafor",
        "cognito_username": "aisha.okafor",
        "cognito_role": "requester",
        "cognito_group": "requester",
        "department": "Lab",
        "erpnext_roles": ["Purchase User", "Stock User", "Employee"],
        "description": "Lab Analyst",
    },
    {
        "email": "demo+wei@example.com",
        "first_name": "Wei", "last_name": "Liu",
        "cognito_username": "wei.liu",
        "cognito_role": "requester",
        "cognito_group": "requester",
        "department": "Quality",
        "erpnext_roles": ["Purchase User", "Stock User", "Employee"],
        "description": "Quality Engineer",
    },
]

# Simulation requesters — also get Cognito accounts (they submit MRs via simulation)
SIMULATION_USERS = [
    {"email": "demo+tom@example.com", "first_name": "Tom", "last_name": "Bradley",
     "cognito_username": "tom.bradley", "cognito_role": "requester", "cognito_group": "requester",
     "department": "Maintenance",
     "erpnext_roles": ["Purchase User", "Stock User", "Employee"], "description": "Maintenance Tech"},
    {"email": "demo+lisa@example.com", "first_name": "Lisa", "last_name": "Park",
     "cognito_username": "lisa.park", "cognito_role": "requester", "cognito_group": "requester",
     "department": "Quality",
     "erpnext_roles": ["Purchase User", "Stock User", "Employee"], "description": "Quality Lab"},
    {"email": "demo+carlos_r@example.com", "first_name": "Carlos", "last_name": "Reyes",
     "cognito_username": "carlos.reyes", "cognito_role": "requester", "cognito_group": "requester",
     "department": "Manufacturing",
     "erpnext_roles": ["Purchase User", "Stock User", "Employee"], "description": "Welding Shop"},
    {"email": "demo+aisha_k@example.com", "first_name": "Aisha", "last_name": "Khan",
     "cognito_username": "aisha.khan", "cognito_role": "requester", "cognito_group": "requester",
     "department": "Engineering",
     "erpnext_roles": ["Purchase User", "Stock User", "Employee"], "description": "Automation"},
    {"email": "demo+dave@example.com", "first_name": "Dave", "last_name": "Morrison",
     "cognito_username": "dave.morrison", "cognito_role": "requester", "cognito_group": "requester",
     "department": "Warehouse",
     "erpnext_roles": ["Purchase User", "Stock User", "Employee"], "description": "Warehouse"},
    {"email": "demo+yuki@example.com", "first_name": "Yuki", "last_name": "Tanaka",
     "cognito_username": "yuki.tanaka", "cognito_role": "requester", "cognito_group": "requester",
     "department": "Manufacturing",
     "erpnext_roles": ["Purchase User", "Stock User", "Employee"], "description": "Assembly Line"},
    {"email": "demo+rachel@example.com", "first_name": "Rachel", "last_name": "Foster",
     "cognito_username": "rachel.foster", "cognito_role": "requester", "cognito_group": "requester",
     "department": "Facilities",
     "erpnext_roles": ["Purchase User", "Stock User", "Employee"], "description": "Facilities"},
]

SERVICE_USERS = [
    {"email": "demo+agent@example.com", "first_name": "P2P", "last_name": "Agent",
     "erpnext_roles": [
         "System Manager", "All",
         "Purchase Manager", "Purchase User",
         "Stock Manager", "Stock User",
         "Accounts Manager", "Accounts User",
         "Manufacturing User",
     ],
     "description": "Service account — full access to all P2P doctypes"},
]


# ══════════════════════════════════════════════════════════════════════════════
# ERPNext USER CREATION
# ══════════════════════════════════════════════════════════════════════════════

def get_erpnext_session() -> requests.Session:
    s = requests.Session()
    # nosemgrep -- use-timeout: demo/setup script; long-running ERPNext calls are expected
    resp = s.post(f"{ERPNEXT_URL}/api/method/login", data={"usr": ERPNEXT_USER, "pwd": ERPNEXT_PASSWORD})
    resp.raise_for_status()
    return s


def create_erpnext_user(session: requests.Session, user: dict) -> bool:
    email = user["email"]
    resp = session.get(f"{ERPNEXT_URL}/api/resource/User/{email}")
    if resp.status_code == 200:
        print(f"  ⏭️  [ERPNext] {email} — already exists")
        return False

    roles = [{"role": r} for r in user["erpnext_roles"]]
    doc = {
        "doctype": "User", "email": email,
        "first_name": user["first_name"], "last_name": user["last_name"],
        "enabled": 1, "new_password": DEFAULT_PASSWORD,
        "roles": roles, "user_type": "System User", "send_welcome_email": 0,
    }
    resp = session.post(f"{ERPNEXT_URL}/api/resource/User", json={"data": json.dumps(doc)})
    if resp.status_code in (409, 417) and "already exists" in resp.text.lower():
        print(f"  ⏭️  [ERPNext] {email} — already exists")
        return False
    resp.raise_for_status()
    print(f"  ✅ [ERPNext] {email} ({user['first_name']} {user['last_name']})")
    return True


def apply_erpnext_fixes(session: requests.Session):
    """Apply Page DocPerm fix (Frappe v15 bug) and enable social login."""
    # Page DocPerm fix
    resp = session.get(
        f"{ERPNEXT_URL}/api/resource/Custom DocPerm",
        params={"filters": json.dumps([["parent", "=", "Page"], ["role", "=", "Employee"]])},
    )
    existing = resp.json().get("data", []) if resp.status_code == 200 else []
    if not existing:
        resp = session.post(
            f"{ERPNEXT_URL}/api/resource/Custom DocPerm",
            json={"data": json.dumps({
                "doctype": "Custom DocPerm", "parent": "Page", "parenttype": "DocType",
                "parentfield": "permissions", "role": "Employee", "read": 1, "permlevel": 0,
            })},
        )
        if resp.status_code == 200:
            print("  🔧 Applied Page DocPerm fix for Employee role")

    # Enable social login
    session.put(
        f"{ERPNEXT_URL}/api/resource/System Settings/System Settings",
        json={"data": json.dumps({"enable_social_login": 1})},
    )


def setup_erpnext(personas, simulation_users, service_users):
    print(f"\n{'='*60}")
    print(f"  ERPNext User Setup ({ERPNEXT_URL})")
    print(f"{'='*60}\n")

    session = get_erpnext_session()
    print(f"  Authenticated as {ERPNEXT_USER}\n")

    created = 0
    print("  Demo Personas:")
    for p in personas:
        if create_erpnext_user(session, p):
            created += 1

    print("\n  Simulation Requesters:")
    for u in simulation_users:
        if create_erpnext_user(session, u):
            created += 1

    print("\n  Service Account:")
    for u in service_users:
        if create_erpnext_user(session, u):
            created += 1

    apply_erpnext_fixes(session)

    total = len(personas) + len(simulation_users) + len(service_users)
    print(f"\n  ERPNext: {created} created, {total - created} already existed")
    return created


# ══════════════════════════════════════════════════════════════════════════════
# COGNITO USER CREATION
# ══════════════════════════════════════════════════════════════════════════════

def get_pool_id_from_cdk(region: str) -> str:
    try:
        import boto3
        cf = boto3.client("cloudformation", region_name=region)
        resp = cf.describe_stacks(StackName="P2PAgenticStack")
        for output in resp["Stacks"][0].get("Outputs", []):
            if output["OutputKey"] == "CognitoUserPoolId":
                return output["OutputValue"]
    except Exception:
        pass  # nosec B110
    return ""


def create_cognito_user(client, pool_id: str, persona: dict, password: str) -> bool:
    # Cognito pool uses signInAliases: email, so username must be the email
    username = persona["email"]
    display_name = persona.get("cognito_username", username)
    try:
        client.admin_create_user(
            UserPoolId=pool_id, Username=username,
            UserAttributes=[
                {"Name": "email", "Value": persona["email"]},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "given_name", "Value": persona.get("first_name", "")},
                {"Name": "family_name", "Value": persona.get("last_name", "")},
                {"Name": "name", "Value": f"{persona.get('first_name', '')} {persona.get('last_name', '')}".strip()},
                {"Name": "custom:role", "Value": persona["cognito_role"]},
                {"Name": "custom:department", "Value": persona.get("department", "")},
            ],
            TemporaryPassword=password, MessageAction="SUPPRESS",
        )
        client.admin_set_user_password(
            UserPoolId=pool_id, Username=username, Password=password, Permanent=True,
        )
        try:
            client.admin_add_user_to_group(
                UserPoolId=pool_id, Username=username, GroupName=persona["cognito_group"],
            )
        except client.exceptions.ResourceNotFoundException:
            # Group doesn't exist yet — non-fatal for user setup.
            pass  # nosec B110

        print(f"  ✅ [Cognito] {username} ({persona['cognito_role']}) — {persona['email']}")
        return True
    except client.exceptions.UsernameExistsException:
        print(f"  ⏭️  [Cognito] {username} — already exists")
        return False
    except Exception as e:
        print(f"  ❌ [Cognito] {username} — {e}")
        return False


def setup_cognito(personas, region: str, pool_id: str, password: str, delete_first: bool):
    import boto3

    pool_id = pool_id or get_pool_id_from_cdk(region)
    if not pool_id:
        print("\n  ⚠️  Cognito: Could not determine User Pool ID.")
        print("     Set --pool-id or deploy P2PAgenticStack first.")
        print("     Skipping Cognito setup.\n")
        return 0

    print(f"\n{'='*60}")
    print(f"  Cognito User Setup (pool: {pool_id})")
    print(f"{'='*60}\n")

    client = boto3.client("cognito-idp", region_name=region)

    if delete_first:
        print("  Deleting existing users...\n")
        for p in personas:
            try:
                client.admin_delete_user(UserPoolId=pool_id, Username=p["email"])
                print(f"  🗑️  Deleted {p['email']}")
            except client.exceptions.UserNotFoundException:
                # Already absent — delete is idempotent.
                pass  # nosec B110
            except Exception as e:
                print(f"  ⚠️  {p['email']}: {e}")
        print()

    created = 0
    for p in personas:
        if create_cognito_user(client, pool_id, p, password):
            created += 1

    print(f"\n  Cognito: {created} created, {len(personas) - created} already existed")
    print(f"  Password: {password}")
    return created


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Create users in ERPNext + Cognito for ARIA P2P demo")
    parser.add_argument("--erpnext-only", action="store_true", help="Only create ERPNext users")
    parser.add_argument("--cognito-only", action="store_true", help="Only create Cognito users")
    parser.add_argument("--pool-id", default="", help="Cognito User Pool ID (auto-detected from CDK if omitted)")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password for all users")
    parser.add_argument("--delete-cognito", action="store_true", help="Delete existing Cognito users first")
    args = parser.parse_args()

    do_erpnext = not args.cognito_only
    do_cognito = not args.erpnext_only

    print(f"\n🔐 ARIA P2P User Setup")
    print(f"   Personas: {len(DEMO_PERSONAS)} demo users")
    if do_erpnext:
        print(f"   ERPNext:  {ERPNEXT_URL}")
    if do_cognito:
        print(f"   Cognito:  {args.region}")

    erp_count = 0
    cog_count = 0

    if do_erpnext:
        erp_count = setup_erpnext(DEMO_PERSONAS, SIMULATION_USERS, SERVICE_USERS)

    if do_cognito:
        # All users with cognito_role get Cognito accounts (demo + simulation)
        all_cognito_users = DEMO_PERSONAS + [u for u in SIMULATION_USERS if "cognito_role" in u]
        cog_count = setup_cognito(all_cognito_users, args.region, args.pool_id, args.password, args.delete_cognito)

    print(f"\n{'='*60}")
    print(f"  ✅ Done!")
    if do_erpnext:
        print(f"     ERPNext: {erp_count} new users")
    if do_cognito:
        print(f"     Cognito: {cog_count} new users")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
