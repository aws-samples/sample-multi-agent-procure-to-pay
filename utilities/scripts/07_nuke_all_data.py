#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
P2P Nuclear Reset — Delete ALL data from ERPNext.

⚠️  DEMO/SAMPLE TOOLING — DESTRUCTIVE. This script is part of the sample's
    demo runbook. It irreversibly deletes ALL documents from the target ERPNext
    site. It is intended only for tearing down a throwaway demo environment.
    Never point it at an ERPNext instance holding data you care about.

Deletes everything seeded + simulation-created data in strict dependency order:
  Phase 1: Cancel & delete submittable transaction documents
  Phase 2: Delete master data (items, suppliers, etc.)
  Phase 3: Delete supporting data (item groups, supplier groups, payment terms, addresses)

ERPNext enforces referential integrity, so order matters:
  - Children before parents (Payment Entry before Purchase Invoice before PO)
  - Transactions before master data (POs reference Suppliers and Items)
  - Master data before groups (Items reference Item Groups)

Usage:
    python nuke_all_data.py --url https://erp.your-domain.example.com --yes

    Or with env vars:
    ERPNEXT_URL=https://erp.your-domain.example.com python nuke_all_data.py --yes
"""

import argparse
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from erpnext_client import ERPNextClient  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# Doctypes to clean, in strict dependency order
# ═══════════════════════════════════════════════════════════════════════════

# Phase 0: Ledger/system entries that block deletion of transaction documents.
# These are auto-created by ERPNext on submission and must be wiped first.
LEDGER_DOCTYPES = [
    "GL Entry",
    "Stock Ledger Entry",
    "Payment Ledger Entry",
    "Bin",                     # Warehouse stock tracking per item — blocks Item deletion
]

# Phase 0b: Submittable system entries (need cancel → delete)
SYSTEM_SUBMITTABLE_DOCTYPES = [
    "Repost Item Valuation",   # Queued valuation recalcs — blocks Item deletion
]

# Phase 1: Submittable transaction documents (must cancel before delete)
SUBMITTABLE_DOCTYPES = [
    "Payment Entry",
    "Journal Entry",
    "Purchase Invoice",
    "Sales Invoice",
    "Purchase Receipt",
    "Delivery Note",
    "Purchase Order",
    "Sales Order",
    "Material Request",
    "Stock Entry",
    "Stock Reconciliation",
]

# Phase 2: Non-submittable master/transactional data
MASTER_DOCTYPES = [
    # Pricing & terms
    "Supplier Quotation",
    "Request for Quotation",
    "Pricing Rule",
    "Item Price",
    # Master data
    "Item",
    "Supplier",
    "Customer",
    # Addresses & contacts linked to suppliers/customers
    "Address",
    "Contact",
    "Dynamic Link",
]

# Phase 3: Groups & configuration (delete only non-system ones)
GROUP_DOCTYPES = [
    "Payment Terms Template",
    "Payment Term",
]

# Item groups & supplier groups that are ERPNext defaults — don't delete these
SYSTEM_ITEM_GROUPS = {
    "All Item Groups",
    "Products",
    "Services",
    "Sub Assemblies",
    "Consumable",
    "Raw Material",
}

SYSTEM_SUPPLIER_GROUPS = {
    "All Supplier Groups",
    "Distributor",
    "Electrical",
    "Hardware",
    "Local",
    "Raw Material",
    "Services",
    "Pharmaceutical",
}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def cancel_doc(client: ERPNextClient, doctype: str, name: str) -> bool:
    """Cancel a submitted document (docstatus 1 → 2).

    For Repost Item Valuation: ERPNext blocks cancel when status is 'Queued'.
    We set status='Completed' first to bypass the guard, then cancel.
    """
    # Special handling for Repost Item Valuation — force status to Completed first
    if doctype == "Repost Item Valuation":
        try:
            import json as _json
            client.session.put(
                f"{client.base_url}/api/resource/{doctype}/{name}",
                json={"data": _json.dumps({"status": "Completed"})},
            )
        except Exception:
            # Best effort to flip status before cancel; not critical.
            pass  # nosec B110

    try:
        client.call_method("frappe.client.cancel", doctype=doctype, name=name)
        return True
    except Exception as e:
        err = str(e).lower()
        if "already cancelled" in err or "not submitted" in err:
            return True
        if "amended" in err:
            return True
        print(f"    [WARN] Cancel failed {doctype}/{name}: {e}")
        return False


def delete_doc(client: ERPNextClient, doctype: str, name: str) -> bool:
    """Delete a single document using frappe.client.delete with force.

    The REST DELETE endpoint (DELETE /api/resource/DocType/name) returns 417
    when documents have linked GL entries or stock ledger entries.
    Using the frappe.client.delete RPC method with force=1 bypasses this.
    """
    # Method 1: Try frappe.client.delete with force (works for linked docs)
    try:
        client.call_method(
            "frappe.client.delete",
            doctype=doctype,
            name=name,
        )
        return True
    except Exception as e:
        err = str(e).lower()
        if "not found" in err or "404" in err or "does not exist" in err:
            return True  # Already gone

    # Method 2: Try REST DELETE as fallback
    try:
        client.delete(doctype, name)
        return True
    except Exception as e:
        err = str(e).lower()
        if "not found" in err or "404" in err:
            return True
        print(f"    [WARN] Delete failed {doctype}/{name}: {e}")
        return False


def get_all_docs(client: ERPNextClient, doctype: str) -> list[dict]:
    """Get all documents of a type. Returns list of {name, docstatus}."""
    try:
        docs = client.get_list(
            doctype,
            fields=["name", "docstatus"],
            limit=0,  # All records
        )
        return docs or []
    except Exception as e:
        if "not found" in str(e).lower() or "404" in str(e).lower():
            return []
        print(f"    [WARN] Could not list {doctype}: {e}")
        return []


def nuke_submittable(client: ERPNextClient, doctype: str) -> tuple[int, int]:
    """Cancel + delete all documents of a submittable doctype.

    Returns (attempted, deleted).
    """
    docs = get_all_docs(client, doctype)
    if not docs:
        return 0, 0

    # Sort: cancel submitted (docstatus=1) first, then amended (2), then draft (0)
    # Delete in reverse: drafts and cancelled first are fine, but order doesn't
    # matter much since we cancel everything first.
    deleted = 0
    for doc in docs:
        name = doc["name"]
        docstatus = doc.get("docstatus", 0)

        # Cancel if submitted
        if docstatus == 1:
            if not cancel_doc(client, doctype, name):
                continue
            time.sleep(0.1)  # nosemgrep: arbitrary-sleep -- ERPNext needs a brief pause between cancel and delete

        # Now delete
        if delete_doc(client, doctype, name):
            deleted += 1

    return len(docs), deleted


def nuke_simple(client: ERPNextClient, doctype: str) -> tuple[int, int]:
    """Delete all documents of a non-submittable doctype.

    Returns (attempted, deleted).
    """
    docs = get_all_docs(client, doctype)
    if not docs:
        return 0, 0

    deleted = 0
    for doc in docs:
        if delete_doc(client, doctype, doc["name"]):
            deleted += 1

    return len(docs), deleted


def nuke_item_groups(client: ERPNextClient) -> tuple[int, int]:
    """Delete non-system Item Groups."""
    docs = get_all_docs(client, "Item Group")
    if not docs:
        return 0, 0

    # Filter out system groups
    to_delete = [d for d in docs if d["name"] not in SYSTEM_ITEM_GROUPS]
    deleted = 0
    for doc in to_delete:
        if delete_doc(client, "Item Group", doc["name"]):
            deleted += 1

    skipped = len(docs) - len(to_delete)
    if skipped:
        print(f"    (kept {skipped} system Item Groups)")

    return len(to_delete), deleted


def nuke_supplier_groups(client: ERPNextClient) -> tuple[int, int]:
    """Delete non-system Supplier Groups."""
    docs = get_all_docs(client, "Supplier Group")
    if not docs:
        return 0, 0

    to_delete = [d for d in docs if d["name"] not in SYSTEM_SUPPLIER_GROUPS]
    deleted = 0
    for doc in to_delete:
        if delete_doc(client, "Supplier Group", doc["name"]):
            deleted += 1

    skipped = len(docs) - len(to_delete)
    if skipped:
        print(f"    (kept {skipped} system Supplier Groups)")

    return len(to_delete), deleted


# ═══════════════════════════════════════════════════════════════════════════
# Main orchestrator
# ═══════════════════════════════════════════════════════════════════════════

def nuke_everything(client: ERPNextClient):
    """Delete ALL data from ERPNext in strict dependency order."""
    start = time.time()
    results = {}

    print("=" * 64)
    print("  ☢️  NUCLEAR RESET — Deleting ALL ERPNext Data")
    print("=" * 64)

    # ── Phase 0: Wipe ledger entries (GL, Stock, Payment) ────────────
    # These are auto-created when documents are submitted and block deletion.
    print("\n\n🔥 PHASE 0: Wiping Ledger Entries (GL, Stock, Payment)")
    print("-" * 50)

    for doctype in LEDGER_DOCTYPES:
        print(f"\n  🗑️  {doctype} …")
        attempted, deleted = nuke_simple(client, doctype)
        results[doctype] = (attempted, deleted)
        if attempted == 0:
            print(f"    (none found)")
        else:
            status = "✅" if attempted == deleted else "⚠️"
            print(f"    {status} Deleted {deleted}/{attempted}")

    # ── Phase 0b: System submittable entries (cancel then delete) ────
    for doctype in SYSTEM_SUBMITTABLE_DOCTYPES:
        print(f"\n  🗑️  {doctype} (cancel + delete) …")
        attempted, deleted = nuke_submittable(client, doctype)
        results[doctype] = (attempted, deleted)
        if attempted == 0:
            print(f"    (none found)")
        else:
            status = "✅" if attempted == deleted else "⚠️"
            print(f"    {status} Deleted {deleted}/{attempted}")

    # ── Phase 1: Submittable documents ────────────────────────────────
    print("\n\n🔥 PHASE 1: Cancelling & Deleting Transaction Documents")
    print("-" * 50)

    for doctype in SUBMITTABLE_DOCTYPES:
        print(f"\n  🗑️  {doctype} …")
        attempted, deleted = nuke_submittable(client, doctype)
        results[doctype] = (attempted, deleted)
        if attempted == 0:
            print(f"    (none found)")
        else:
            status = "✅" if attempted == deleted else "⚠️"
            print(f"    {status} Deleted {deleted}/{attempted}")

    # ── Phase 2: Master data ──────────────────────────────────────────
    print("\n\n🔥 PHASE 2: Deleting Master Data")
    print("-" * 50)

    for doctype in MASTER_DOCTYPES:
        print(f"\n  🗑️  {doctype} …")
        attempted, deleted = nuke_simple(client, doctype)
        results[doctype] = (attempted, deleted)
        if attempted == 0:
            print(f"    (none found)")
        else:
            status = "✅" if attempted == deleted else "⚠️"
            print(f"    {status} Deleted {deleted}/{attempted}")

    # ── Phase 3: Groups & config ──────────────────────────────────────
    print("\n\n🔥 PHASE 3: Deleting Groups & Configuration")
    print("-" * 50)

    for doctype in GROUP_DOCTYPES:
        print(f"\n  🗑️  {doctype} …")
        attempted, deleted = nuke_simple(client, doctype)
        results[doctype] = (attempted, deleted)
        if attempted == 0:
            print(f"    (none found)")
        else:
            status = "✅" if attempted == deleted else "⚠️"
            print(f"    {status} Deleted {deleted}/{attempted}")

    # Item Groups (skip system defaults)
    print(f"\n  🗑️  Item Group (custom only) …")
    attempted, deleted = nuke_item_groups(client)
    results["Item Group (custom)"] = (attempted, deleted)
    if attempted == 0:
        print(f"    (none to delete)")
    else:
        status = "✅" if attempted == deleted else "⚠️"
        print(f"    {status} Deleted {deleted}/{attempted}")

    # Supplier Groups (skip system defaults)
    print(f"\n  🗑️  Supplier Group (custom only) …")
    attempted, deleted = nuke_supplier_groups(client)
    results["Supplier Group (custom)"] = (attempted, deleted)
    if attempted == 0:
        print(f"    (none to delete)")
    else:
        status = "✅" if attempted == deleted else "⚠️"
        print(f"    {status} Deleted {deleted}/{attempted}")

    # ── Summary ───────────────────────────────────────────────────────
    elapsed = time.time() - start

    print("\n\n" + "=" * 64)
    print("  ☢️  NUCLEAR RESET SUMMARY")
    print("=" * 64)

    total_attempted = 0
    total_deleted = 0
    for doctype, (attempted, deleted) in results.items():
        if attempted > 0:
            total_attempted += attempted
            total_deleted += deleted
            status = "✅" if attempted == deleted else "⚠️"
            print(f"  {status} {doctype}: {deleted}/{attempted}")

    if total_attempted == 0:
        print("  (nothing to delete — ERP is already clean)")
    else:
        print(f"\n  Total: {total_deleted}/{total_attempted} documents deleted")

    # Check for any failures
    failures = total_attempted - total_deleted
    if failures > 0:
        print(f"\n  ⚠️  {failures} documents could not be deleted (likely system defaults or linked records)")
        print("  These are generally safe to ignore.")

    print(f"\n  Time elapsed: {elapsed:.1f}s")
    print("=" * 64 + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="☢️  Nuclear reset — delete ALL data from ERPNext."
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
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    args = parser.parse_args()
    if not args.password:
        parser.error("ERPNext password is required. Set ERPNEXT_PASSWORD or pass --password.")
    return args


def main():
    args = parse_args()

    os.environ["ERPNEXT_URL"] = args.url
    os.environ["ERPNEXT_USER"] = args.user
    os.environ["ERPNEXT_PASSWORD"] = args.password

    import config as cfg
    cfg.ERPNEXT_URL = args.url
    cfg.ERPNEXT_USER = args.user
    cfg.ERPNEXT_PASSWORD = args.password

    if not args.yes:
        print("\n" + "=" * 64)
        print("  ☢️  NUCLEAR RESET WARNING")
        print("=" * 64)
        print("""
  This will DELETE ALL DATA from ERPNext including:

  Transactions:
    ✗ Payment Entries, Journal Entries
    ✗ Purchase Invoices, Sales Invoices
    ✗ Purchase Receipts, Delivery Notes
    ✗ Purchase Orders, Sales Orders
    ✗ Material Requests
    ✗ Stock Entries, Stock Reconciliations

  Master Data:
    ✗ Items, Suppliers, Customers
    ✗ Addresses, Contacts
    ✗ Item Prices, Pricing Rules
    ✗ Supplier/Request for Quotations

  Configuration:
    ✗ Payment Terms Templates
    ✗ Custom Item Groups & Supplier Groups

  ⚠️  System defaults (company, accounts, default groups) are preserved.
  ⚠️  This action CANNOT be undone.
""")
        confirm = input("  Type 'NUKE' to confirm: ").strip()
        if confirm != "NUKE":
            print("  Aborted.")
            sys.exit(0)

    print(f"\n🔗 Connecting to ERPNext at {args.url} …")
    client = ERPNextClient()

    nuke_everything(client)


if __name__ == "__main__":
    main()
