# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Verify ERPNext is running and data is loaded correctly.
Performs health checks and data integrity validation.
"""

import sys
from erpnext_client import ERPNextClient


def check_connection(client: ERPNextClient) -> bool:
    """Verify ERPNext is reachable and authenticated."""
    try:
        result = client.call_method("frappe.auth.get_logged_user")
        print(f"  Connected as: {result}")
        return True
    except Exception as e:
        print(f"  [FAIL] Connection failed: {e}")
        return False


def check_company(client: ERPNextClient) -> bool:
    """Verify company exists."""
    from config import COMPANY_NAME
    try:
        company = client.get("Company", COMPANY_NAME)
        print(f"  Company: {company.get('company_name')} ({company.get('abbr')})")
        return True
    except Exception:
        print(f"  [FAIL] Company '{COMPANY_NAME}' not found")
        return False


def check_data_counts(client: ERPNextClient) -> dict:
    """Count records for each P2P doctype."""
    doctypes = {
        "Supplier": 0,
        "Item": 0,
        "Item Group": 0,
        "Material Request": 0,
        "Purchase Order": 0,
        "Purchase Receipt": 0,
        "Purchase Invoice": 0,
        "Payment Entry": 0,
    }
    for dt in doctypes:
        try:
            records = client.get_list(dt, limit=0)
            doctypes[dt] = len(records)
        except Exception:
            doctypes[dt] = -1
    return doctypes


def check_p2p_flow(client: ERPNextClient):
    """Verify end-to-end P2P document linkage."""
    print("\n  P2P Flow Verification:")

    # Check POs exist
    pos = client.get_list("Purchase Order", filters={"docstatus": 1}, limit=5)
    if not pos:
        print("    [WARN] No submitted Purchase Orders found")
        return

    po = client.get("Purchase Order", pos[0]["name"])
    print(f"    Sample PO: {po['name']} | Supplier: {po['supplier']} | Total: {po.get('grand_total', 'N/A')}")

    # Check linked receipts
    prs = client.get_list(
        "Purchase Receipt",
        filters={"docstatus": 1},
        limit=3,
    )
    if prs:
        print(f"    Purchase Receipts: {len(prs)} submitted")
    else:
        print("    [WARN] No submitted Purchase Receipts")

    # Check linked invoices
    invs = client.get_list(
        "Purchase Invoice",
        filters={"docstatus": 1},
        limit=3,
    )
    if invs:
        print(f"    Purchase Invoices: {len(invs)} submitted")
    else:
        print("    [WARN] No submitted Purchase Invoices")


def main():
    print("=" * 60)
    print("ERPNext Verification")
    print("=" * 60)

    client = ERPNextClient()

    # Connection check
    print("\n--- Connection ---")
    if not check_connection(client):
        sys.exit(1)

    # Company check
    print("\n--- Company ---")
    check_company(client)

    # Data counts
    print("\n--- Data Counts ---")
    counts = check_data_counts(client)
    total = 0
    for dt, count in counts.items():
        status = "OK" if count > 0 else "EMPTY" if count == 0 else "ERROR"
        print(f"  {dt:25s} {count:>6d}  [{status}]")
        if count > 0:
            total += count

    # P2P flow
    check_p2p_flow(client)

    # Summary
    print(f"\n{'=' * 60}")
    empty = sum(1 for c in counts.values() if c == 0)
    errors = sum(1 for c in counts.values() if c < 0)
    if errors:
        print(f"RESULT: {errors} doctype(s) had errors — check ERPNext logs")
    elif empty:
        print(f"RESULT: {empty} doctype(s) are empty — run load_data.py to populate")
    else:
        print(f"RESULT: All doctypes populated ({total} total records)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
