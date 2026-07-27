#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
P2P Demo Data Reset Script.

⚠️  DEMO/SAMPLE TOOLING — DESTRUCTIVE. Part of the sample's demo runbook.
    Deletes transactional documents from the target ERPNext site. Intended
    only for resetting a throwaway demo environment between runs.

Deletes all transactional documents created during a demo run, then re-seeds
ERPNext to the baseline state. Master data (suppliers, items) is preserved.

Deletion order respects ERPNext document dependencies:
  1. Payment Entries (cancel + delete)
  2. Purchase Invoices (cancel + delete)
  3. Purchase Receipts (cancel + delete)
  4. Purchase Orders (cancel + delete)
  5. Material Requests (cancel + delete)

After deletion, re-runs seed_demo_data.py to restore the baseline narrative.

Usage:
    python reset_demo.py

    Or with explicit connection args:
    python reset_demo.py --url https://erp.example.com --user Administrator --password "$ERPNEXT_PASSWORD"

Flags:
    --skip-reseed   Only delete; don't re-seed afterwards
    --yes           Skip confirmation prompt
"""

import argparse
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
UTILITIES_DIR = SCRIPT_DIR.parent
DATA_DIR = UTILITIES_DIR / "data"

sys.path.insert(0, str(SCRIPT_DIR))

from erpnext_client import ERPNextClient  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# Document cleanup (cancel → delete, in dependency order)
# ═══════════════════════════════════════════════════════════════════════════

# Doctypes to clean, in the order they must be deleted
# (children before parents to avoid dependency errors)
DOCTYPES_TO_CLEAN = [
    "Payment Entry",
    "Purchase Invoice",
    "Purchase Receipt",
    "Purchase Order",
    "Material Request",
]


def cancel_document(client: ERPNextClient, doctype: str, name: str) -> bool:
    """Cancel a submitted document (docstatus 1 → 2)."""
    try:
        client.call_method(
            "frappe.client.cancel",
            doctype=doctype,
            name=name,
        )
        return True
    except Exception as e:
        # Some documents may already be cancelled or in draft
        if "already cancelled" in str(e).lower() or "not submitted" in str(e).lower():
            return True
        print(f"    [WARN] Could not cancel {doctype} {name}: {e}")
        return False


def delete_document(client: ERPNextClient, doctype: str, name: str) -> bool:
    """Delete a document."""
    try:
        client.delete(doctype, name)
        return True
    except Exception as e:
        print(f"    [WARN] Could not delete {doctype} {name}: {e}")
        return False


def clean_doctype(client: ERPNextClient, doctype: str) -> tuple[int, int]:
    """Cancel and delete all documents of a given doctype.

    Returns (attempted, succeeded) counts.
    """
    # Get all documents (submitted and draft)
    docs = client.get_list(
        doctype,
        fields=["name", "docstatus"],
        limit=0,
    )

    if not docs:
        return 0, 0

    attempted = len(docs)
    succeeded = 0

    for doc in docs:
        name = doc["name"]
        docstatus = doc.get("docstatus", 0)

        # Cancel if submitted (docstatus=1)
        if docstatus == 1:
            if not cancel_document(client, doctype, name):
                continue

        # Delete the document
        if delete_document(client, doctype, name):
            succeeded += 1

    return attempted, succeeded


def clean_all_transactions(client: ERPNextClient) -> dict:
    """Delete all transactional documents in dependency order."""
    results = {}

    for doctype in DOCTYPES_TO_CLEAN:
        print(f"\n  🗑️  Cleaning {doctype} …")
        attempted, succeeded = clean_doctype(client, doctype)
        results[doctype] = {"attempted": attempted, "succeeded": succeeded}

        if attempted == 0:
            print(f"    (none found)")
        else:
            print(f"    Deleted {succeeded}/{attempted}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Main reset flow
# ═══════════════════════════════════════════════════════════════════════════

def reset_demo(client: ERPNextClient, skip_reseed: bool = False):
    """Full demo reset: clean transactions, then optionally re-seed."""
    start = time.time()

    print("=" * 60)
    print("  Apex Manufacturing Group — Demo Data Reset")
    print("=" * 60)

    # ── Phase 1: Delete all transactional documents ──────────────────
    print("\n🧹 PHASE 1: Cleaning Transactional Documents")
    results = clean_all_transactions(client)

    # Print summary
    print("\n" + "-" * 40)
    print("  Cleanup Summary:")
    total_attempted = 0
    total_succeeded = 0
    for doctype, counts in results.items():
        a, s = counts["attempted"], counts["succeeded"]
        total_attempted += a
        total_succeeded += s
        status = "✅" if a == s else "⚠️"
        if a > 0:
            print(f"  {status} {doctype}: {s}/{a} deleted")
    print(f"\n  Total: {total_succeeded}/{total_attempted} documents cleaned")

    # ── Phase 2: Re-seed (optional) ──────────────────────────────────
    if skip_reseed:
        print("\n⏭️  Skipping re-seed (--skip-reseed flag)")
    else:
        print("\n\n🌱 PHASE 2: Re-seeding Demo Data")
        print("-" * 40)

        # Import and run the seed script
        from seed_demo_data import seed_all, load_narrative  # noqa: E402

        # Load narrative JSON
        import json
        narrative_path = DATA_DIR / "01_suppliers.json"  # migrated from demo_narrative.json
        with open(narrative_path, encoding="utf-8") as f:
            data = json.load(f)

        seed_all(client, data)

    # ── Done ─────────────────────────────────────────────────────────
    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print(f"  🔄 RESET COMPLETE ({elapsed:.1f}s)")
    print("=" * 60 + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="Reset P2P demo data in ERPNext to baseline state."
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
        "--skip-reseed",
        action="store_true",
        help="Only delete transactional data; don't re-seed afterwards.",
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

    # Override config module env vars if CLI args provided
    os.environ["ERPNEXT_URL"] = args.url
    os.environ["ERPNEXT_USER"] = args.user
    os.environ["ERPNEXT_PASSWORD"] = args.password

    import config as cfg
    cfg.ERPNEXT_URL = args.url
    cfg.ERPNEXT_USER = args.user
    cfg.ERPNEXT_PASSWORD = args.password

    # Confirmation prompt
    if not args.yes:
        print("\n⚠️  This will DELETE all transactional documents in ERPNext:")
        print("   - Payment Entries")
        print("   - Purchase Invoices")
        print("   - Purchase Receipts")
        print("   - Purchase Orders")
        print("   - Material Requests")
        if not args.skip_reseed:
            print("\n   Then re-seed with baseline demo data.")
        print()
        confirm = input("   Continue? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("   Aborted.")
            sys.exit(0)

    print(f"\n🔗 Connecting to ERPNext at {args.url} …")
    client = ERPNextClient()

    reset_demo(client, skip_reseed=args.skip_reseed)


if __name__ == "__main__":
    main()
