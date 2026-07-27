#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
P2P Demo Data Seed Script — file-based.

Loads all data from numbered JSON files in utilities/data/:
  01_suppliers.json       — 22 suppliers
  02_item_groups.json     — 14 item groups (hierarchical)
  03_items.json           — 60 items
  04_material_requests.json — 20 material requests
  06_payment_terms.json   — 6 payment terms templates

Company: Apex Manufacturing Group (AMG)
Warehouse: Stores - AMG

Transactions are created under persona identities:
  - Maria (demo+maria) → Material Requests

Note: POs, GRs, invoices, and payments are NOT seeded here — those are
created by the P2P agents during normal workflow execution.

Usage:
    python seed_demo_data.py --url https://erp.your-domain.example.com
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
UTILITIES_DIR = SCRIPT_DIR.parent
DATA_DIR = UTILITIES_DIR / "data"

sys.path.insert(0, str(SCRIPT_DIR))

from erpnext_client import ERPNextClient  # noqa: E402

# ── Company constants ────────────────────────────────────────────────────
COMPANY = "Apex Manufacturing Group"
ABBR = "AMG"
CURRENCY = "USD"
WAREHOUSE = "Stores - AMG"

# ── Persona config ───────────────────────────────────────────────────────
PERSONA_PASSWORD = os.getenv("ERPNEXT_USER_PASSWORD")
if not PERSONA_PASSWORD:
    raise RuntimeError(
        "ERPNEXT_USER_PASSWORD is not set. Use the same value you set when "
        "running 02_setup_users.py (export ERPNEXT_USER_PASSWORD=... or set "
        "it in utilities/.env)."
    )
PERSONA_MARIA = "demo+maria@example.com"


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def load_json(filename: str) -> list | dict:
    path = DATA_DIR / filename
    if not path.exists():
        print(f"  [SKIP] {filename} not found")
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def upsert(client, doctype, name, data):
    if client.exists(doctype, name):
        return client.get(doctype, name)
    result = client.insert(doctype, data)
    if result:
        print(f"  [OK] {doctype}: {name}")
    return result or {}


def submit(client, doctype, name):
    try:
        client.submit(doctype, name)
        return True
    except Exception as e:
        err = str(e).lower()
        if "already submitted" in err:
            return True
        print(f"  [WARN] Submit {doctype}/{name}: {e}")
        return False


def get_persona_client(email):
    """Create an ERPNext client authenticated as a specific persona user.

    Uses session login (username/password) since per-user API keys
    are managed by the Lambda adapter, not the seed scripts.
    """
    import requests as _req
    import config as cfg
    base_url = cfg.ERPNEXT_URL.rstrip("/")
    try:
        s = _req.Session()
        # nosemgrep -- use-timeout: demo/setup script; long-running ERPNext calls are expected
        resp = s.post(f"{base_url}/api/method/login",
                      data={"usr": email, "pwd": PERSONA_PASSWORD})
        resp.raise_for_status()
        print(f"  🔑 {email}")
        # Create a minimal client-like object that uses this session
        client = ERPNextClient.__new__(ERPNextClient)
        client.base_url = base_url
        client.session = s
        return client
    except Exception as e:
        print(f"  [WARN] Login failed for {email} ({e}), using admin")
        return ERPNextClient()


# ═══════════════════════════════════════════════════════════════════════════
# Phase functions
# ═══════════════════════════════════════════════════════════════════════════

def seed_item_groups(client):
    groups = load_json("02_item_groups.json")
    if not groups:
        return
    print(f"\n📦 Item Groups ({len(groups)}) …")
    for g in groups:
        is_parent = any(eg.get("parent") == g["name"] for eg in groups)
        upsert(client, "Item Group", g["name"], {
            "item_group_name": g["name"],
            "parent_item_group": g.get("parent", "All Item Groups"),
            "is_group": 1 if is_parent else 0,
        })


def seed_payment_terms(client):
    terms = load_json("06_payment_terms.json")
    if not terms:
        return
    print(f"\n💳 Payment Terms ({len(terms)}) …")
    for pt in terms:
        name = pt["name"]
        if client.exists("Payment Terms Template", name):
            continue
        term_rows = []
        for t in pt["terms"]:
            row = {
                "payment_term": name,
                "invoice_portion": t["invoice_portion"],
                "credit_days": t["credit_days"],
                "credit_days_based_on": "Day(s) after invoice date",
            }
            # Early-pay discount fields (e.g., "2/10 Net 30" = 2% if paid in 10 days)
            if t.get("discount_percentage"):
                row["discount"] = t["discount_percentage"]
                row["discount_validity"] = t.get("discount_validity", 10)
                row["discount_validity_based_on"] = t.get(
                    "discount_validity_based_on", "Day(s) after invoice date"
                )
            term_rows.append(row)
        result = client.insert("Payment Terms Template", {
            "template_name": name,
            "terms": term_rows,
        })
        if result:
            print(f"  [OK] Payment Terms: {name}")


def seed_suppliers(client):
    suppliers = load_json("01_suppliers.json")
    if not suppliers:
        return
    print(f"\n🏭 Suppliers ({len(suppliers)}) …")
    seen_groups = set()
    for s in suppliers:
        group = s.get("supplier_group", "Raw Material")
        if group not in seen_groups:
            if not client.exists("Supplier Group", group):
                client.insert("Supplier Group", {"supplier_group_name": group})
            seen_groups.add(group)
    for s in suppliers:
        upsert(client, "Supplier", s["supplier_name"], {
            "supplier_name": s["supplier_name"],
            "supplier_group": s.get("supplier_group", "Raw Material"),
            "country": s.get("country", "United States"),
            "default_currency": s.get("default_currency", "USD"),
            "supplier_type": s.get("supplier_type", "Company"),
            "disabled": s.get("disabled", 0),
        })


def seed_items(client):
    items = load_json("03_items.json")
    if not items:
        return
    print(f"\n📋 Items ({len(items)}) …")
    for item in items:
        code = item["item_code"]
        upsert(client, "Item", code, {
            "item_code": code,
            "item_name": item["item_name"],
            "item_group": item.get("item_group", "Raw Material"),
            "stock_uom": item.get("stock_uom", "Nos"),
            "standard_rate": item.get("standard_rate", 0),
            "is_stock_item": item.get("is_stock_item", 1),
            "description": item.get("description", item["item_name"]),
            "default_warehouse": WAREHOUSE,
        })


def seed_custom_fields(client):
    """Add cost_center and department custom fields to Material Request."""
    for fieldname, opts in [
        ("cost_center", {"fieldtype": "Link", "options": "Cost Center",
                         "label": "Cost Center", "insert_after": "company",
                         "allow_on_submit": 1, "in_list_view": 1, "in_standard_filter": 1}),
        ("department", {"fieldtype": "Link", "options": "Department",
                        "label": "Department", "insert_after": "cost_center",
                        "allow_on_submit": 1}),
    ]:
        cf_name = f"Material Request-{fieldname}"
        if client.exists("Custom Field", cf_name):
            continue
        result = client.insert("Custom Field", {"dt": "Material Request", "fieldname": fieldname, **opts})
        if result:
            print(f"  [OK] Custom Field: {cf_name}")


def seed_budgets(client):
    """Create Cost Centers and Budgets from 07_budgets.json."""
    data = load_json("07_budgets.json")
    if not data:
        return
    cost_centers = data.get("cost_centers", [])
    budgets = data.get("budgets", [])
    fiscal_year = data.get("fiscal_year", "2026")

    print(f"\n💰 Cost Centers ({len(cost_centers)}) + Budgets ({len(budgets)}) …")

    # Use company root as parent (it's a group node)
    company_root = f"{COMPANY} - {ABBR}"

    # Create Departments + Cost Centers (1:1 mapping)
    for cc in cost_centers:
        dept_name = f"{cc['name']} - {ABBR}"
        upsert(client, "Department", dept_name, {
            "department_name": cc["name"],
            "company": COMPANY,
            "is_group": 0,
        })

    # Create leaf cost centers directly under company root
    for cc in cost_centers:
        cc_name = f"{cc['name']} - {ABBR}"
        upsert(client, "Cost Center", cc_name, {
            "cost_center_name": cc["name"],
            "company": COMPANY,
            "is_group": 0,
            "parent_cost_center": company_root,
        })

    # Ensure fiscal year exists
    if not client.exists("Fiscal Year", fiscal_year):
        upsert(client, "Fiscal Year", fiscal_year, {
            "year": fiscal_year,
            "year_start_date": f"{fiscal_year}-01-01",
            "year_end_date": f"{fiscal_year}-12-31",
        })

    # Find the COGS account
    # ERPNext names accounts as "Account Name - ABBR"
    cogs_account = f"Cost of Goods Sold - {ABBR}"

    # Create budgets
    for b in budgets:
        cc_name = f"{b['cost_center']} - {ABBR}"
        budget_name = f"BUD-{fiscal_year}-{b['cost_center']}"

        if client.exists("Budget", budget_name):
            print(f"  [SKIP] Budget: {budget_name}")
            continue

        result = client.insert("Budget", {
            "name": budget_name,
            "cost_center": cc_name,
            "fiscal_year": fiscal_year,
            "company": COMPANY,
            "budget_against": "Cost Center",
            "action_if_annual_budget_exceeded": "Warn",
            "action_if_accumulated_monthly_budget_exceeded": "Warn",
            "accounts": [{
                "account": cogs_account,
                "budget_amount": b["budget_amount"],
            }],
        })
        if result:
            print(f"  [OK] Budget: {budget_name} → {cc_name} = ${b['budget_amount']:,.0f}")
            submit(client, "Budget", result["name"])


PERSONA_MAP = {
    "maria": PERSONA_MARIA,
    "lisa": "demo+lisa@example.com",
    "carlos": "demo+carlos@example.com",
    "aisha": "demo+aisha@example.com",
    "rachel": "demo+rachel@example.com",
    "dave": "demo+dave@example.com",
}


def seed_material_requests(admin_client):
    """Create Material Requests from 04_material_requests.json.

    Each MR specifies a _persona field — the MR is created under that user's
    ERPNext identity so owner-based filtering works correctly.
    """
    mr_defs = load_json("04_material_requests.json")
    if not mr_defs:
        return 0
    print(f"\n📋 Material Requests ({len(mr_defs)}) …")
    count = 0
    persona_clients = {}  # cache per-persona clients

    for mr_def in mr_defs:
        persona = mr_def.get("_persona", "maria")
        email = PERSONA_MAP.get(persona, PERSONA_MARIA)

        # Get or create persona client
        if email not in persona_clients:
            try:
                persona_clients[email] = get_persona_client(email)
            except Exception:
                persona_clients[email] = admin_client

        client = persona_clients[email]

        items = [{
            "item_code": it["item_code"],
            "qty": it["qty"],
            "rate": it.get("rate", 0),
            "warehouse": WAREHOUSE,
            "schedule_date": mr_def.get("schedule_date", mr_def["transaction_date"]),
            "description": it.get("description", ""),
        } for it in mr_def["items"]]

        mr_data = {
            "material_request_type": mr_def.get("material_request_type", "Purchase"),
            "company": COMPANY,
            "transaction_date": mr_def["transaction_date"],
            "schedule_date": mr_def.get("schedule_date", mr_def["transaction_date"]),
            "items": items,
        }
        if mr_def.get("department"):
            mr_data["department"] = mr_def["department"]
        if mr_def.get("cost_center"):
            mr_data["cost_center"] = mr_def["cost_center"]

        result = client.insert("Material Request", mr_data)
        if result:
            scenario = mr_def.get("_scenario", "")
            print(f"  [OK] MR {result['name']} ({persona}: {scenario[:50]})")
            submit(client, "Material Request", result["name"])
            count += 1
        else:
            print(f"  [WARN] MR failed for {persona}")
    return count


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Seed ERPNext with P2P demo data.")
    parser.add_argument("--url", default=os.getenv("ERPNEXT_URL", "http://localhost:8080"))
    parser.add_argument("--user", default=os.getenv("ERPNEXT_USER", "Administrator"))
    parser.add_argument("--password", default=os.getenv("ERPNEXT_PASSWORD"))
    args = parser.parse_args()

    if not args.password:
        parser.error(
            "ERPNext admin password is required. Set ERPNEXT_PASSWORD in your "
            "environment or pass --password."
        )

    os.environ["ERPNEXT_URL"] = args.url
    os.environ["ERPNEXT_USER"] = args.user
    os.environ["ERPNEXT_PASSWORD"] = args.password
    import config as cfg
    cfg.ERPNEXT_URL = args.url
    cfg.ERPNEXT_USER = args.user
    cfg.ERPNEXT_PASSWORD = args.password

    start = time.time()
    print(f"🔗 Connecting to {args.url} …")
    admin = ERPNextClient()

    print("\n" + "=" * 60)
    print("  Apex Manufacturing Group — Demo Data Seed")
    print("=" * 60)

    # Phase 1: Master Data (admin)
    print("\n🔧 PHASE 1: Master Data")
    seed_custom_fields(admin)
    seed_item_groups(admin)
    seed_payment_terms(admin)
    seed_suppliers(admin)
    seed_items(admin)
    seed_budgets(admin)

    # Phase 2: Transactions (persona users)
    # Note: POs, GRs, invoices, and payments are NOT seeded — those are
    # created by the P2P agents during normal workflow execution.
    print("\n\n🔧 PHASE 2: Transactions (persona sessions)")
    mr_count = seed_material_requests(admin)

    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print("  ✅ SEED COMPLETE")
    print("=" * 60)
    print(f"""
  Master Data: 22 suppliers, 60 items, 14 item groups, 6 payment terms
  Transactions:
    Material Requests: {mr_count}
  Time: {elapsed:.1f}s
""")

    # Save timestamp
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / ".seed_timestamp", "w", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    main()
