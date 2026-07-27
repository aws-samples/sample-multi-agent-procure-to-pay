#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
P2P Demo Data Verification Script.

Validates that all seed data was loaded correctly into ERPNext.
Checks master data (suppliers, items) and transactional documents
(POs, receipts, invoices, payments, material requests) against
the expected counts and states from the demo narrative.

Usage:
    python verify_demo_data.py

    Or with explicit connection args:
    python verify_demo_data.py --url https://erp.example.com --user Administrator --password "$ERPNEXT_PASSWORD"

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
UTILITIES_DIR = SCRIPT_DIR.parent
DATA_DIR = UTILITIES_DIR / "data"
# Legacy file removed — data now in 01-06 numbered files

sys.path.insert(0, str(SCRIPT_DIR))

from erpnext_client import ERPNextClient  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# Verification helpers
# ═══════════════════════════════════════════════════════════════════════════

def get_count(client: ERPNextClient, doctype: str, filters: list | None = None) -> int:
    """Count documents of a given doctype, optionally filtered."""
    filter_dict = {}
    if filters:
        # Convert list-of-lists filter format to dict for the get_list call
        for f in filters:
            if len(f) == 3:
                field, op, value = f
                filter_dict[field] = [op, value]
    docs = client.get_list(
        doctype,
        filters=filter_dict if filter_dict else None,
        fields=["name"],
        limit=0,
    )
    return len(docs)


def check_supplier_details(client: ERPNextClient) -> list[str]:
    """Verify specific supplier attributes across the diverse supplier set."""
    errors = []

    # Check that "Blocked Vendor Inc" is actually disabled
    try:
        blocked = client.get("Supplier", "Blocked Vendor Inc")
        if not blocked.get("disabled"):
            errors.append("Blocked Vendor Inc should be disabled=1 but is not")
    except Exception:
        errors.append("Blocked Vendor Inc not found")

    # Check that Acme Industrial Supply exists and is active
    try:
        acme = client.get("Supplier", "Acme Industrial Supply")
        if acme.get("disabled"):
            errors.append("Acme Industrial Supply should be enabled but is disabled")
    except Exception:
        errors.append("Acme Industrial Supply not found")

    # Check EuroTech Automation (international supplier)
    try:
        eurotech = client.get("Supplier", "EuroTech Automation")
        if eurotech.get("country") != "Germany":
            errors.append(
                f"EuroTech Automation country should be 'Germany', "
                f"got '{eurotech.get('country')}'"
            )
    except Exception:
        errors.append("EuroTech Automation not found")

    # Check Global Parts Co (China-based)
    try:
        gpc = client.get("Supplier", "Global Parts Co")
        if gpc.get("country") != "China":
            errors.append(
                f"Global Parts Co country should be 'China', "
                f"got '{gpc.get('country')}'"
            )
    except Exception:
        errors.append("Global Parts Co not found")

    # Check Pacific Manufacturing (Japan-based)
    try:
        pacific = client.get("Supplier", "Pacific Manufacturing")
        if pacific.get("country") != "Japan":
            errors.append(
                f"Pacific Manufacturing country should be 'Japan', "
                f"got '{pacific.get('country')}'"
            )
    except Exception:
        errors.append("Pacific Manufacturing not found")

    return errors


def check_item_details(client: ERPNextClient) -> list[str]:
    """Verify specific item attributes across all 5 categories."""
    errors = []

    expected_items = {
        "MAT-RM-001": {"item_name": "Steel Rod 10mm x 1m", "item_group": "Raw Material"},
        "MAT-RM-003": {"item_name": "Welding Wire ER70S-6 1.2mm", "item_group": "Raw Material", "stock_uom": "Kg"},
        "MAT-SP-001": {"item_name": "Air Filter Element AF-200", "item_group": "Spare Parts"},
        "MAT-SP-003": {"item_name": "Conveyor Belt Section 500mm x 10m", "item_group": "Spare Parts"},
        "MAT-CP-002": {"item_name": "Electric Motor 2HP 3-Phase", "item_group": "Components"},
        "MAT-CP-003": {"item_name": "PLC Module IO-16 Digital", "item_group": "Components"},
        "MAT-CN-001": {"item_name": "Industrial Lubricant ISO VG 68 5L", "item_group": "Consumables"},
        "MAT-SF-001": {"item_name": "Safety Goggles SG-Pro Anti-Fog", "item_group": "Safety Equipment"},
        "MAT-SF-003": {"item_name": "Steel-Toe Safety Boots Size 10", "item_group": "Safety Equipment"},
    }

    for code, expected in expected_items.items():
        try:
            item = client.get("Item", code)
            if item.get("item_name") != expected["item_name"]:
                errors.append(
                    f"{code}: expected item_name='{expected['item_name']}', "
                    f"got '{item.get('item_name')}'"
                )
            if item.get("item_group") != expected["item_group"]:
                errors.append(
                    f"{code}: expected item_group='{expected['item_group']}', "
                    f"got '{item.get('item_group')}'"
                )
            if "stock_uom" in expected and item.get("stock_uom") != expected["stock_uom"]:
                errors.append(
                    f"{code}: expected stock_uom='{expected['stock_uom']}', "
                    f"got '{item.get('stock_uom')}'"
                )
        except Exception:
            errors.append(f"Item {code} ({expected['item_name']}) not found")

    return errors


def check_transaction_integrity(client: ERPNextClient) -> list[str]:
    """Verify transactional document relationships and states."""
    errors = []

    # Check that POs exist and some have linked receipts
    pos = client.get_list(
        "Purchase Order",
        filters={"docstatus": ["=", 1]},
        fields=["name", "per_received", "supplier"],
        limit=0,
    )

    if not pos:
        errors.append("No submitted Purchase Orders found")
        return errors

    received_pos = [po for po in pos if po.get("per_received", 0) > 0]
    if not received_pos:
        errors.append("No Purchase Orders have any receipts (per_received > 0)")

    # Check multiple suppliers appear in PO history
    po_suppliers = set(po.get("supplier", "") for po in pos)
    if len(po_suppliers) < 4:
        errors.append(
            f"Expected POs from at least 4 different suppliers, got {len(po_suppliers)}: "
            f"{', '.join(po_suppliers)}"
        )

    # Check for unpaid invoices (Priya's 3-way match demo)
    unpaid_invoices = client.get_list(
        "Purchase Invoice",
        filters={"docstatus": ["=", 1], "outstanding_amount": [">", 0]},
        fields=["name", "outstanding_amount", "supplier"],
        limit=0,
    )
    if not unpaid_invoices:
        errors.append("No unpaid Purchase Invoices found (needed for Priya's 3-way match demo)")

    # Check for pending Material Requests (Sarah's approval demo)
    pending_mrs = client.get_list(
        "Material Request",
        filters={"docstatus": ["=", 1], "material_request_type": ["=", "Purchase"]},
        fields=["name"],
        limit=0,
    )
    if not pending_mrs:
        errors.append("No pending Material Requests found (needed for Sarah's approval demo)")

    # Check for multi-line Material Request (conveyor overhaul)
    for mr in pending_mrs:
        mr_doc = client.get("Material Request", mr["name"])
        if len(mr_doc.get("items", [])) >= 3:
            break
    else:
        errors.append("No multi-line Material Request found (conveyor overhaul scenario)")

    return errors


# ═══════════════════════════════════════════════════════════════════════════
# Main verification
# ═══════════════════════════════════════════════════════════════════════════

def verify(client: ERPNextClient) -> bool:
    """Run all verification checks and print results."""

    print("=" * 64)
    print("  Apex Manufacturing Group — Demo Data Verification")
    print("=" * 64)

    all_pass = True

    # ── Count checks ─────────────────────────────────────────────────
    print("\n📊 Document Count Checks:\n")

    checks = {
        "Suppliers (total)": (8, get_count(client, "Supplier")),
        "Suppliers (active)": (7, get_count(client, "Supplier", [["disabled", "=", 0]])),
        "Suppliers (blocked)": (1, get_count(client, "Supplier", [["disabled", "=", 1]])),
        "Items (MAT-*)": (20, get_count(client, "Item", [["item_code", "like", "MAT-%"]])),
        "Items (Raw Material)": (
            5,
            get_count(client, "Item", [["item_code", "like", "MAT-RM-%"]]),
        ),
        "Items (Spare Parts)": (
            4,
            get_count(client, "Item", [["item_code", "like", "MAT-SP-%"]]),
        ),
        "Items (Components)": (
            5,
            get_count(client, "Item", [["item_code", "like", "MAT-CP-%"]]),
        ),
        "Items (Consumables)": (
            3,
            get_count(client, "Item", [["item_code", "like", "MAT-CN-%"]]),
        ),
        "Items (Safety Equipment)": (
            3,
            get_count(client, "Item", [["item_code", "like", "MAT-SF-%"]]),
        ),
        "Purchase Orders (submitted)": (
            7,
            get_count(client, "Purchase Order", [["docstatus", "=", 1]]),
        ),
        "Purchase Receipts (submitted)": (
            7,
            get_count(client, "Purchase Receipt", [["docstatus", "=", 1]]),
        ),
        "Purchase Invoices (submitted)": (
            6,
            get_count(client, "Purchase Invoice", [["docstatus", "=", 1]]),
        ),
        "Purchase Invoices (unpaid)": (
            2,
            get_count(
                client,
                "Purchase Invoice",
                [["docstatus", "=", 1], ["outstanding_amount", ">", 0]],
            ),
        ),
        "Payment Entries (submitted)": (
            4,
            get_count(client, "Payment Entry", [["docstatus", "=", 1]]),
        ),
        "Material Requests (submitted)": (
            3,
            get_count(client, "Material Request", [["docstatus", "=", 1]]),
        ),
    }

    for name, (expected, actual) in checks.items():
        if actual >= expected:
            status = "✅"
        else:
            status = "❌"
            all_pass = False
        print(f"  {status} {name}: expected ≥{expected}, got {actual}")

    # ── Supplier detail checks ───────────────────────────────────────
    print("\n🏭 Supplier Detail Checks:\n")
    supplier_errors = check_supplier_details(client)
    if supplier_errors:
        all_pass = False
        for err in supplier_errors:
            print(f"  ❌ {err}")
    else:
        print("  ✅ All supplier details correct (US, China, Japan, Germany)")

    # ── Item detail checks ───────────────────────────────────────────
    print("\n📋 Item Detail Checks:\n")
    item_errors = check_item_details(client)
    if item_errors:
        all_pass = False
        for err in item_errors:
            print(f"  ❌ {err}")
    else:
        print("  ✅ All item details correct (5 categories, mixed UOMs)")

    # ── Transaction integrity checks ─────────────────────────────────
    print("\n🔗 Transaction Integrity Checks:\n")
    txn_errors = check_transaction_integrity(client)
    if txn_errors:
        all_pass = False
        for err in txn_errors:
            print(f"  ❌ {err}")
    else:
        print("  ✅ All transaction relationships intact")

    # ── Demo scenario readiness ──────────────────────────────────────
    print("\n🎭 Demo Scenario Readiness:\n")

    scenarios = {
        "Maria (Requester)": "20 items available across 5 categories for new requisitions",
        "Sarah (Approver)": "3 pending Material Requests available for approval workflow",
        "Jake (PO Manager)": "6+ active suppliers with pricing history for PO creation",
        "Priya (AP)": "2 unpaid invoices (1 standard, 1 price discrepancy) for 3-way match",
        "Gary (Executive)": "7 POs, 6 invoices, 4 payments across 6 suppliers for analytics",
    }

    scenario_checks = {
        "Maria (Requester)": get_count(client, "Item", [["item_code", "like", "MAT-%"]]) >= 20,
        "Sarah (Approver)": get_count(client, "Material Request", [["docstatus", "=", 1]]) >= 3,
        "Jake (PO Manager)": get_count(client, "Supplier", [["disabled", "=", 0]]) >= 6,
        "Priya (AP)": get_count(
            client,
            "Purchase Invoice",
            [["docstatus", "=", 1], ["outstanding_amount", ">", 0]],
        )
        >= 2,
        "Gary (Executive)": (
            get_count(client, "Payment Entry", [["docstatus", "=", 1]]) >= 4
            and get_count(client, "Purchase Order", [["docstatus", "=", 1]]) >= 7
        ),
    }

    for persona, ready in scenario_checks.items():
        desc = scenarios[persona]
        if ready:
            print(f"  ✅ {persona}: {desc}")
        else:
            print(f"  ❌ {persona}: {desc}")
            all_pass = False

    # ── Final result ─────────────────────────────────────────────────
    print("\n" + "=" * 64)
    if all_pass:
        print("  🎉 ALL CHECKS PASSED — Demo data is ready!")
    else:
        print("  ⚠️  SOME CHECKS FAILED — Re-run seed_demo_data.py")
    print("=" * 64 + "\n")

    return all_pass


# ═══════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="Verify P2P demo data in ERPNext."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("ERPNEXT_URL", "http://localhost:8080"),
        help="ERPNext URL (default: $ERPNEXT_URL or http://localhost:8080)",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("ERPNEXT_USER", "Administrator"),
        help="ERPNext username (default: $ERPNEXT_USER or Administrator)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("ERPNEXT_PASSWORD"),
        help="ERPNext password (default: $ERPNEXT_PASSWORD; required)",
    )
    args = parser.parse_args()
    if not args.password:
        parser.error("ERPNext password is required. Set ERPNEXT_PASSWORD or pass --password.")
    return args


def main():
    args = parse_args()

    # Override config module env vars if CLI args provided
    os.environ["ERPNEXT_URL"] = args.url
    os.environ["ERPNEXT_USER"] = args.user
    os.environ["ERPNEXT_PASSWORD"] = args.password

    import config as cfg
    cfg.ERPNEXT_URL = args.url
    cfg.ERPNEXT_USER = args.user
    cfg.ERPNEXT_PASSWORD = args.password

    print(f"🔗 Connecting to ERPNext at {args.url} …\n")
    client = ERPNextClient()

    passed = verify(client)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
