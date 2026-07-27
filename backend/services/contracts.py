# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Framework agreements and blanket purchase orders.

Single source of truth for negotiated-contract data, consumed by:
  - the Sourcing and PO Management agents (contract-aware supplier scoring), via
    ``get_active_agreements`` / ``get_blanket_po`` (see backend/agents/*).
  - the Configuration view API (``/api/config/contracts``), via ``list_contracts``.

For this sample the agreements are demo data defined here. In a real deployment
this module would query the ERP's contract/blanket-order records (e.g. ERPNext
Blanket Order) through the canonical adapter — the function signatures below are
the seam to swap that in without touching the agents.

Matching is deliberately fuzzy: agents pass an item/material group derived from a
requisition (e.g. ``"FASTENERS"``, ``"Fasteners & Hardware"``) which won't always
equal a contract's ``material_group`` (``"Fasteners"``) verbatim. We match
case-insensitively on a shared significant token so contracts still resolve.
"""

from __future__ import annotations

import re

# Demo framework agreements + blanket POs. FA-* are framework agreements;
# BPO-* are blanket purchase orders (distinguished by the id prefix).
_CONTRACTS: list[dict] = [
    {
        "agreement_id": "FA-2024-001",
        "vendor": "Acme Industrial Supply",
        "material_group": "Fasteners",
        "discount_pct": 12,
        "total_value": 500000,
        "utilized_value": 342500,
        "start_date": "2024-01-01",
        "end_date": "2025-12-31",
        "status": "active",
    },
    {
        "agreement_id": "FA-2024-002",
        "vendor": "Midwest Fasteners Inc",
        "material_group": "Fasteners",
        "discount_pct": 15,
        "total_value": 250000,
        "utilized_value": 198000,
        "start_date": "2024-03-01",
        "end_date": "2025-12-31",
        "status": "active",
    },
    {
        "agreement_id": "FA-2024-003",
        "vendor": "National Bearings Co",
        "material_group": "Bearings & Filters",
        "discount_pct": 8,
        "total_value": 300000,
        "utilized_value": 187000,
        "start_date": "2024-01-15",
        "end_date": "2025-06-30",
        "status": "active",
    },
    {
        "agreement_id": "FA-2024-004",
        "vendor": "ElectroParts Direct",
        "material_group": "Electrical / PLC",
        "discount_pct": 10,
        "total_value": 400000,
        "utilized_value": 380000,
        "start_date": "2024-02-01",
        "end_date": "2025-12-31",
        "status": "active",
    },
    {
        "agreement_id": "FA-2024-005",
        "vendor": "SafetyFirst Equipment",
        "material_group": "Safety Equipment",
        "discount_pct": 5,
        "total_value": 150000,
        "utilized_value": 45000,
        "start_date": "2024-06-01",
        "end_date": "2026-05-31",
        "status": "active",
    },
    {
        "agreement_id": "BPO-2024-001",
        "vendor": "Global Steel Supply",
        "material_group": "Steel & Raw Material",
        "discount_pct": 7,
        "total_value": 800000,
        "utilized_value": 520000,
        "start_date": "2024-01-01",
        "end_date": "2025-12-31",
        "status": "active",
    },
]

# Tokens too generic to match a group on (avoid "Safety Equipment" matching
# "Equipment" against unrelated groups, etc.).
_STOPWORDS = {"and", "the", "of", "material", "materials", "equipment", "parts",
              "components", "supplies", "hardware", "misc", "general"}


def _tokens(text: str) -> set[str]:
    """Lowercased significant word tokens of a group name."""
    words = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {w for w in words if w and w not in _STOPWORDS and len(w) > 2}


def _group_matches(query: str, contract_group: str) -> bool:
    """True if the query group and a contract's material_group share a token.

    Case-insensitive and tolerant of the naming drift between requisition item
    groups and contract material groups (e.g. ``"FASTENERS"`` ~ ``"Fasteners"``,
    ``"Bearings & Seals"`` ~ ``"Bearings & Filters"``).
    """
    q, c = _tokens(query), _tokens(contract_group)
    if not q or not c:
        return False
    return bool(q & c)


def list_contracts() -> list[dict]:
    """Return all framework agreements + blanket POs (used by the config view)."""
    return list(_CONTRACTS)


def _blanket_po(c: dict) -> bool:
    return str(c.get("agreement_id", "")).upper().startswith("BPO")


def get_active_agreements(
    material_group: str | None = None,
    contract_type: str | None = None,
) -> list[dict]:
    """Return active agreements, optionally filtered by group and/or type.

    Args:
        material_group: Item/material group to match (fuzzy, case-insensitive).
            None returns all groups.
        contract_type: ``"FRAMEWORK"`` for framework agreements (FA-*),
            ``"BLANKET"`` for blanket POs (BPO-*). None returns both.
    """
    results = [c for c in _CONTRACTS if c.get("status") == "active"]
    if contract_type:
        want_blanket = contract_type.upper() in ("BLANKET", "BPO", "BLANKET_PO")
        results = [c for c in results if _blanket_po(c) == want_blanket]
    if material_group:
        results = [c for c in results if _group_matches(material_group, c["material_group"])]
    return results


def get_blanket_po(vendor: str, material_group: str) -> dict | None:
    """Return the active blanket PO for a vendor + material group, or None.

    Args:
        vendor: Supplier name / id to match (case-insensitive).
        material_group: Item/material group to match (fuzzy).
    """
    vendor_norm = (vendor or "").strip().lower()
    for c in _CONTRACTS:
        if not _blanket_po(c) or c.get("status") != "active":
            continue
        if c["vendor"].strip().lower() != vendor_norm:
            continue
        if material_group and not _group_matches(material_group, c["material_group"]):
            continue
        remaining = c.get("total_value", 0) - c.get("utilized_value", 0)
        return {**c, "found": True, "remaining_value": remaining}
    return None
