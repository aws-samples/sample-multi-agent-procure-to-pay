# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Simulation engine configuration — weights, timing, env vars.

Loads data exclusively from the numbered JSON files in utilities/data/:
  01_suppliers.json, 02_item_groups.json, 03_items.json, 06_payment_terms.json
"""

import json
import os
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# Load catalog data from numbered JSON files
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent.parent / "data"

_SUPPLIERS_PATH = _DATA_DIR / "01_suppliers.json"
_ITEMS_PATH = _DATA_DIR / "03_items.json"
_ITEM_GROUPS_PATH = _DATA_DIR / "02_item_groups.json"
_PAYMENT_TERMS_PATH = _DATA_DIR / "06_payment_terms.json"

_CATALOG_SUPPLIERS = []
if _SUPPLIERS_PATH.exists():
    with open(_SUPPLIERS_PATH, encoding="utf-8") as f:
        _CATALOG_SUPPLIERS = json.load(f)

_CATALOG_ITEMS = []
if _ITEMS_PATH.exists():
    with open(_ITEMS_PATH, encoding="utf-8") as f:
        _CATALOG_ITEMS = json.load(f)

_CATALOG_GROUPS = []
if _ITEM_GROUPS_PATH.exists():
    with open(_ITEM_GROUPS_PATH, encoding="utf-8") as f:
        _CATALOG_GROUPS = json.load(f)

_CATALOG_PAYMENT_TERMS = []
if _PAYMENT_TERMS_PATH.exists():
    with open(_PAYMENT_TERMS_PATH, encoding="utf-8") as f:
        _CATALOG_PAYMENT_TERMS = json.load(f)

# Build item templates from catalog items (03_items.json)
ITEM_TEMPLATES = []
_seen_codes = set()
for item in _CATALOG_ITEMS:
    code = item.get("item_code", "")
    if code and code not in _seen_codes:
        base_price = item.get("standard_rate", 10.0)
        ITEM_TEMPLATES.append((
            code,
            item.get("item_name", code),
            item.get("item_group", "MRO Supplies"),
            item.get("stock_uom", "Nos"),
            round(base_price * 0.85, 2),
            round(base_price * 1.15, 2),
        ))
        _seen_codes.add(code)

# Build supplier profiles from catalog suppliers (01_suppliers.json)
SUPPLIER_PROFILES = []
_seen_suppliers = set()
for sup in _CATALOG_SUPPLIERS:
    name = sup.get("supplier_name", "")
    if name and name not in _seen_suppliers and not sup.get("disabled"):
        categories = sup.get("_meta", {}).get("categories", ["MRO Supplies"])
        SUPPLIER_PROFILES.append((
            name,
            sup.get("supplier_group", "Raw Material"),
            sup.get("country", "United States"),
            sup.get("default_currency", "USD"),
            categories,
        ))
        _seen_suppliers.add(name)

# Item groups from catalog (02_item_groups.json)
ITEM_GROUPS = [g.get("name", "") for g in _CATALOG_GROUPS if g.get("name")]

# Payment terms from catalog (06_payment_terms.json)
PAYMENT_TERMS = [pt.get("name", "") for pt in _CATALOG_PAYMENT_TERMS if pt.get("name")]
if not PAYMENT_TERMS:
    PAYMENT_TERMS = ["Net 15", "Net 30", "Net 45"]

# Diverse requester pool — simulation creates PRs from different factory roles.
# Each has a name, email, department, typical request pattern, and preferred item groups.
# The preferred_groups field drives department-aware item selection so each requester
# orders items relevant to their role (not random items from the entire catalog).
REQUESTERS = [
    {"name": "Maria Chen", "email": "demo+maria@example.com", "dept": "Production", "pattern": "raw materials, components",
     "preferred_groups": ["Raw Material", "Components", "Fasteners & Hardware", "Packaging Materials"]},
    {"name": "Tom Bradley", "email": "demo+tom@example.com", "dept": "Maintenance", "pattern": "spare parts, seal kits, belts",
     "preferred_groups": ["Spare Parts", "Bearings & Seals", "Hydraulic Components", "MRO Supplies"]},
    {"name": "Lisa Park", "email": "demo+lisa@example.com", "dept": "Quality Lab", "pattern": "consumables, calibration supplies",
     "preferred_groups": ["Consumables", "MRO Supplies", "Office Supplies", "Lubricants & Chemicals"]},
    {"name": "Carlos Reyes", "email": "demo+carlos@example.com", "dept": "Welding Shop", "pattern": "welding wire, raw materials, PPE",
     "preferred_groups": ["Raw Material", "Safety Equipment", "Consumables", "MRO Supplies"]},
    {"name": "Aisha Khan", "email": "demo+aisha@example.com", "dept": "Automation", "pattern": "PLCs, sensors, motors",
     "preferred_groups": ["Electrical Components", "Components", "Conveyor Parts", "Spare Parts"]},
    {"name": "Dave Morrison", "email": "demo+dave@example.com", "dept": "Warehouse", "pattern": "safety equipment, lubricants",
     "preferred_groups": ["Safety Equipment", "Lubricants & Chemicals", "Packaging Materials", "MRO Supplies"]},
    {"name": "Yuki Tanaka", "email": "demo+yuki@example.com", "dept": "Assembly Line", "pattern": "bearings, fasteners, components",
     "preferred_groups": ["Bearings & Seals", "Fasteners & Hardware", "Components", "Conveyor Parts"]},
    {"name": "Rachel Foster", "email": "demo+rachel@example.com", "dept": "Facilities", "pattern": "safety boots, goggles, gloves",
     "preferred_groups": ["Safety Equipment", "Office Supplies", "MRO Supplies", "Lubricants & Chemicals"]},
]

# Build an index of ITEM_TEMPLATES by item_group for efficient department-aware lookup
ITEMS_BY_GROUP: dict[str, list[tuple]] = {}
for _item_tpl in ITEM_TEMPLATES:
    _group = _item_tpl[2]  # item_group is index 2 in the tuple
    ITEMS_BY_GROUP.setdefault(_group, []).append(_item_tpl)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

CANONICAL_API_URL = os.environ.get("CANONICAL_API_URL", "http://localhost:8000")
SIMULATION_TABLE = os.environ.get("SIMULATION_TABLE", "p2p-dev-simulation-state")
AWS_REGION = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "us-east-1"))

# AgentCore Runtime ARNs (optional — agent triggering is skipped if empty)
AGENTCORE_ARNS = {
    "requisition": os.environ.get("AGENTCORE_REQUISITION_ARN", ""),
    "sourcing": os.environ.get("AGENTCORE_SOURCING_ARN", ""),
    "po_management": os.environ.get("AGENTCORE_PO_MANAGEMENT_ARN", ""),
    "receiving": os.environ.get("AGENTCORE_RECEIVING_ARN", ""),
    "invoice_matching": os.environ.get("AGENTCORE_INVOICE_MATCHING_ARN", ""),
    "payment": os.environ.get("AGENTCORE_PAYMENT_ARN", ""),
    "workflow": os.environ.get("AGENTCORE_WORKFLOW_ARN", ""),
}

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

TICK_INTERVAL_MINUTES = 3
MAX_CONCURRENT_SCENARIOS = 10
NEW_SCENARIO_PROBABILITY = 0.4  # 40% chance per tick to start a new scenario

# Delays between scenario steps (seconds)
STEP_DELAYS = {
    "PENDING_to_REQ_CREATED": 0,
    "REQ_CREATED_to_AGENT_ANALYZED": 30,
    "AGENT_ANALYZED_to_PO_CREATED": 15,
    "PO_CREATED_to_RECEIPT_CREATED": 120,
    "RECEIPT_CREATED_to_INVOICE_CREATED": 180,
    "INVOICE_CREATED_to_AGENT_MATCHED": 30,
    "AGENT_MATCHED_to_PAYMENT_CREATED": 60,
}

# TTL for completed scenarios (24 hours)
SCENARIO_TTL_SECONDS = 86400

# ---------------------------------------------------------------------------
# Scenario weights (must sum to 100)
# ---------------------------------------------------------------------------

SCENARIO_WEIGHTS = {
    "happy_path": 30,
    "price_variance": 10,
    "short_delivery": 10,
    "high_value_escalation": 10,
    "quantity_mismatch": 8,
    "late_delivery": 8,
    "partial_invoice": 7,
    "multi_line_complex": 7,
    "duplicate_requisition": 5,
    "payment_discount": 5,
}

# ---------------------------------------------------------------------------
# Helpers for picking items and suppliers
# ---------------------------------------------------------------------------


def find_suppliers_for_group(item_group: str) -> list[tuple]:
    """Return supplier profiles whose categories include the given item group."""
    matches = [
        sp for sp in SUPPLIER_PROFILES
        if item_group in sp[4]
    ]
    return matches if matches else SUPPLIER_PROFILES[:3]


def pick_random_items(count: int = 3) -> list[dict]:
    """Pick random items from ITEM_TEMPLATES with generated prices."""
    if not ITEM_TEMPLATES:
        return [{"item_code": "MAT-RM-001", "item_name": "Steel Rod", "item_group": "Raw Material",
                 "uom": "Nos", "unit_price": 45.00}]

    selected = random.sample(ITEM_TEMPLATES, min(count, len(ITEM_TEMPLATES)))
    items = []
    for code, name, group, uom, min_p, max_p in selected:
        items.append({
            "item_code": code,
            "item_name": name,
            "item_group": group,
            "uom": uom,
            "unit_price": round(random.uniform(min_p, max_p), 2),  # nosec B311
        })
    return items


def pick_supplier_for_items(items: list[dict]) -> tuple:
    """Pick the best-matching supplier for a set of items based on categories."""
    if not SUPPLIER_PROFILES:
        return ("Acme Industrial Supply", "Raw Material", "United States", "USD", [])

    groups = {item["item_group"] for item in items}
    best_match = None
    best_score = -1
    for sp in SUPPLIER_PROFILES:
        score = len(groups.intersection(set(sp[4])))
        if score > best_score:
            best_score = score
            best_match = sp
    return best_match or random.choice(SUPPLIER_PROFILES)  # nosec B311
