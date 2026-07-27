# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Simulation Engine — generates realistic human-driven events in the P2P pipeline.

Two modes, triggered by separate EventBridge schedules:

1. DEMAND GENERATOR (every 6 hours):
   Creates 1-3 Material Requests from a pool of 8 requesters.
   This simulates factory workers, maintenance techs, and lab staff
   submitting purchase requests throughout the workday.

2. EVENT SCANNER (every 5 minutes):
   Scans ERPNext for documents needing the next human action:
   - POs awaiting delivery → Creates Purchase Receipts (after shipping delay)
   - POs with GR but no invoice → Generates vendor invoice PDFs (after billing delay)
   This simulates warehouse staff receiving goods and vendors emailing invoices.

Everything else (PR analysis, sourcing, PO creation, 3-way match, payment)
is handled by the agentic workflows triggered by these events.
"""

import json
import logging
import os
import random
from datetime import datetime, timedelta

import boto3

from .api_client import CanonicalAPIClient, STEP_USER_MAP
from .config import (
    AWS_REGION,
    ITEM_TEMPLATES,
    ITEMS_BY_GROUP,
    MAX_CONCURRENT_SCENARIOS,
    REQUESTERS,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_api_client: CanonicalAPIClient | None = None

# Track recently used item codes per requester email to avoid repetition.
# Key: requester email, Value: set of item_codes used in recent PRs.
# Bounded to last 20 items per user. Resets on Lambda cold start (acceptable).
_recently_used_items: dict[str, list[str]] = {}
_MAX_RECENT_ITEMS = 20

USE_LLM = os.environ.get("SIMULATION_USE_LLM", "false").lower() == "true"

# ─── Configurable delays (hours) ─────────────────────────────────────────────
# These simulate realistic shipping and billing timelines.
# Override via environment variables for faster/slower demo pacing.

MIN_SHIPPING_DELAY_HOURS = int(os.environ.get("SIM_MIN_SHIPPING_HOURS", "4"))
MAX_SHIPPING_DELAY_HOURS = int(os.environ.get("SIM_MAX_SHIPPING_HOURS", "48"))
MIN_BILLING_DELAY_HOURS = int(os.environ.get("SIM_MIN_BILLING_HOURS", "12"))
MAX_BILLING_DELAY_HOURS = int(os.environ.get("SIM_MAX_BILLING_HOURS", "72"))


def _get_api_client() -> CanonicalAPIClient:
    global _api_client
    if _api_client is None:
        _api_client = CanonicalAPIClient()
    return _api_client


# ═══════════════════════════════════════════════════════════════════════════════
# MODE 1: DEMAND GENERATOR — creates Material Requests
# Triggered every 6 hours by EventBridge
# ═══════════════════════════════════════════════════════════════════════════════


def tick_demand(force_pr_count: int | None = None) -> dict:
    """Create 1-3 Material Requests from random requesters.

    Args:
        force_pr_count: If set, create exactly this many PRs (for testing).
    """
    summary = {"mode": "demand", "material_requests_created": 0, "errors": 0}

    if force_pr_count is not None:
        num_prs = max(0, min(force_pr_count, 5))
    else:
        num_prs = random.choices([1, 2, 3], weights=[50, 35, 15], k=1)[0]  # nosec B311

    for _ in range(num_prs):
        try:
            result = _generate_material_request()
            if result:
                summary["material_requests_created"] += 1
        except Exception as e:
            logger.error("PR creation failed: %s", e)
            summary["errors"] += 1

    logger.info("Demand tick complete: %s", summary)
    return summary


def _generate_material_request() -> dict | None:
    """Create a Material Request from a random requester.

    Uses department-aware item selection: each requester's preferred_groups
    drives which items appear in their MR, avoiding repetition of recently
    ordered items.
    """
    api = _get_api_client()
    requester = random.choice(REQUESTERS)  # nosec B311

    if USE_LLM:
        try:
            from .llm_generator import generate_requisition as llm_gen
            # Filter LLM item pool to the requester's preferred groups
            preferred = set(requester.get("preferred_groups", []))
            if preferred:
                items_for_llm = [
                    {"item_code": t[0], "item_name": t[1], "item_group": t[2],
                     "uom": t[3], "standard_rate": t[5]}
                    for t in ITEM_TEMPLATES if t[2] in preferred
                ]
            else:
                items_for_llm = [
                    {"item_code": t[0], "item_name": t[1], "item_group": t[2],
                     "uom": t[3], "standard_rate": t[5]}
                    for t in ITEM_TEMPLATES
                ]

            # Pick a scenario relevant to the requester's department
            dept_scenarios = {
                "Production": [
                    "routine restock of raw materials for the production floor",
                    "new batch run requires additional components and fasteners",
                    "packaging material restock for Q2 shipping schedule",
                ],
                "Maintenance": [
                    "urgent maintenance repair — hydraulic press line 2 is down",
                    "preventive maintenance on CNC machines — bearing and seal kits",
                    "scheduled replacement of worn spare parts on conveyor line",
                ],
                "Quality Lab": [
                    "lab equipment calibration supplies for quarterly audit",
                    "consumables restock for quality testing station",
                    "replacement chemicals for surface testing procedures",
                ],
                "Welding Shop": [
                    "welding shop material restock for Q2 production run",
                    "safety equipment refresh for welding team per OSHA schedule",
                    "raw material restock — steel rods and plate for fabrication",
                ],
                "Automation": [
                    "new automation project for conveyor line upgrade",
                    "PLC replacement and sensor calibration for line 3",
                    "electrical component restock for automation lab",
                ],
                "Warehouse": [
                    "warehouse safety equipment annual refresh",
                    "lubricant and chemical restock for warehouse operations",
                    "packaging material reorder for shipping department",
                ],
                "Assembly Line": [
                    "bearing and seal replacement for assembly stations",
                    "fastener restock — bolts, nuts, and washers running low",
                    "conveyor belt components for scheduled maintenance",
                ],
                "Facilities": [
                    "scheduled quarterly safety equipment refresh — PPE",
                    "office supply reorder for facilities management",
                    "cleaning and maintenance chemical restock",
                ],
            }
            scenarios = dept_scenarios.get(requester["dept"], [
                "routine restock of consumables for the production floor",
                "general MRO supplies replenishment",
            ])
            scenario = random.choice(scenarios)  # nosec B311

            req_data = llm_gen(scenario, items_for_llm)
            logger.info("LLM generated PR for %s (%s): %s", requester["name"], requester["dept"], scenario[:50])
        except Exception as e:
            logger.warning("LLM generation failed, using template: %s", e)
            req_data = _template_requisition(requester)
    else:
        req_data = _template_requisition(requester)

    # Ensure cost_center and department are always set from the requester's dept.
    # The LLM path doesn't produce these fields, and _template_requisition may
    # evolve — so always stamp them here as the single source of truth.
    # Same pattern the chat agent uses: dept → cost_center lookup.
    _DEPT_CC_MAP = {
        "Production": {"department": "Manufacturing - AMG", "cost_center": "Manufacturing - AMG"},
        "Maintenance": {"department": "Maintenance - AMG", "cost_center": "Maintenance - AMG"},
        "Quality Lab": {"department": "Engineering - AMG", "cost_center": "Engineering - AMG"},
        "Welding Shop": {"department": "Manufacturing - AMG", "cost_center": "Manufacturing - AMG"},
        "Automation": {"department": "Engineering - AMG", "cost_center": "Engineering - AMG"},
        "Warehouse": {"department": "Operations - AMG", "cost_center": "Operations - AMG"},
        "Assembly Line": {"department": "Manufacturing - AMG", "cost_center": "Manufacturing - AMG"},
        "Facilities": {"department": "Safety - AMG", "cost_center": "Safety - AMG"},
    }
    requester_dept = requester.get("dept", "Production")
    dept_cc = _DEPT_CC_MAP.get(requester_dept, {"department": "Operations - AMG", "cost_center": "Operations - AMG"})
    req_data.setdefault("cost_center", dept_cc["cost_center"])
    req_data.setdefault("department", dept_cc["department"])

    # Track which items this requester just ordered (for anti-repetition)
    email = requester["email"]
    ordered_codes = [li["item_id"] for li in req_data.get("line_items", [])]
    recent = _recently_used_items.setdefault(email, [])
    recent.extend(ordered_codes)
    # Keep only the last N items to bound memory
    if len(recent) > _MAX_RECENT_ITEMS:
        _recently_used_items[email] = recent[-_MAX_RECENT_ITEMS:]

    try:
        result = api.create_requisition(req_data, requester_email=requester["email"])
        req_id = result.get("requisition_id") or result.get("name", "")
        logger.info("Created Material Request %s by %s (%s) — items: %s",
                     req_id, requester["name"], requester["dept"], ordered_codes)
        return {"requisition_id": req_id, "requester": requester}
    except Exception as e:
        logger.error("Failed to create Material Request: %s", e)
        return None


def _template_requisition(requester: dict | None = None) -> dict:
    """Generate a department-aware, diversified Material Request.

    Item selection strategy:
    1. Build a candidate pool from the requester's preferred_groups
    2. Exclude items this requester recently ordered (anti-repetition)
    3. If the preferred pool is exhausted, spill over into adjacent groups
    4. 20% chance of including one "wild card" item from outside preferences
       (simulates cross-department emergency requests)
    """
    num_items = random.randint(1, 4)  # nosec B311
    required_date = (datetime.now() + timedelta(days=random.randint(7, 30))).strftime("%Y-%m-%d")  # nosec B311

    # Get requester's preferred groups (or use all groups as fallback)
    preferred_groups = requester.get("preferred_groups", []) if requester else []
    requester_email = requester.get("email", "") if requester else ""
    recently_used = set(_recently_used_items.get(requester_email, []))

    # Build candidate pool: items from preferred groups, excluding recently used
    candidates = []
    if preferred_groups:
        for group in preferred_groups:
            for item_tpl in ITEMS_BY_GROUP.get(group, []):
                if item_tpl[0] not in recently_used:  # item_code is index 0
                    candidates.append(item_tpl)

    # If preferred pool is too small (all recently used), add items from ALL groups
    # but still exclude recently used items
    if len(candidates) < num_items:
        for item_tpl in ITEM_TEMPLATES:
            if item_tpl[0] not in recently_used and item_tpl not in candidates:
                candidates.append(item_tpl)

    # Last resort: if everything has been used recently, just use the full catalog
    if len(candidates) < num_items:
        candidates = list(ITEM_TEMPLATES)

    # Shuffle and select
    random.shuffle(candidates)
    selected = candidates[:num_items]

    # 20% chance: replace one item with a "wild card" from outside preferred groups
    # This simulates cross-department emergency requests (e.g., maintenance needing safety gear)
    if preferred_groups and len(selected) > 1 and random.random() < 0.20:  # nosec B311
        non_preferred = [t for t in ITEM_TEMPLATES if t[2] not in preferred_groups]
        if non_preferred:
            wild_card = random.choice(non_preferred)  # nosec B311
            replace_idx = random.randint(0, len(selected) - 1)  # nosec B311
            selected[replace_idx] = wild_card
            logger.debug("Wild card item inserted: %s (%s)", wild_card[0], wild_card[2])

    # Map requester department to matching cost center
    # Department names must include " - AMG" suffix (ERPNext company abbreviation)
    dept_cc_map = {
        "Production": {"department": "Manufacturing - AMG", "cost_center": "Manufacturing - AMG"},
        "Maintenance": {"department": "Maintenance - AMG", "cost_center": "Maintenance - AMG"},
        "Quality Lab": {"department": "Engineering - AMG", "cost_center": "Engineering - AMG"},
        "Welding Shop": {"department": "Manufacturing - AMG", "cost_center": "Manufacturing - AMG"},
        "Automation": {"department": "Engineering - AMG", "cost_center": "Engineering - AMG"},
        "Warehouse": {"department": "Operations - AMG", "cost_center": "Operations - AMG"},
        "Assembly Line": {"department": "Manufacturing - AMG", "cost_center": "Manufacturing - AMG"},
        "Facilities": {"department": "Safety - AMG", "cost_center": "Safety - AMG"},
    }

    # Department-specific purpose templates
    dept_purposes = {
        "Production": [
            "Production line restock — standard monthly order",
            "New batch run starting next week — raw material replenishment",
            "Component shortage on line 2 — expedited restock",
        ],
        "Maintenance": [
            "Preventive maintenance kit for Q2 scheduled shutdown",
            "Urgent repair — hydraulic system failure on press #4",
            "Scheduled bearing and seal replacement — conveyor maintenance",
        ],
        "Quality Lab": [
            "Lab consumables restock for quality testing",
            "Calibration supplies for quarterly compliance audit",
            "Surface treatment chemicals replenishment",
        ],
        "Welding Shop": [
            "Welding shop material restock for Q2 production run",
            "PPE refresh for welding team — quarterly schedule",
            "Raw material order for custom fabrication job #2847",
        ],
        "Automation": [
            "PLC replacement project — line 3 automation upgrade",
            "Sensor and motor inventory restock for automation lab",
            "Conveyor upgrade project — electrical components phase 2",
        ],
        "Warehouse": [
            "Safety equipment annual refresh per OSHA requirements",
            "Lubricant and chemical restock for warehouse equipment",
            "Packaging material reorder for Q2 shipping volume increase",
        ],
        "Assembly Line": [
            "Assembly station maintenance — bearing and fastener restock",
            "Fastener inventory running low — standard reorder",
            "Conveyor belt component replacement — scheduled maintenance",
        ],
        "Facilities": [
            "Quarterly PPE refresh — gloves, goggles, safety boots",
            "Office supply reorder for facilities management",
            "Building maintenance chemicals and cleaning supplies",
        ],
    }

    requester_dept = requester.get("dept", "Production") if requester else "Production"
    dept_cc = dept_cc_map.get(requester_dept, {"department": "Operations - AMG", "cost_center": "Operations - AMG"})
    purposes = dept_purposes.get(requester_dept, ["General procurement request"])

    line_items = []
    for i, (code, name, group, uom, min_p, max_p) in enumerate(selected):
        line_items.append({
            "line_number": i + 1,
            "item_id": code,
            "quantity": random.randint(5, 200),  # nosec B311
            "unit_of_measure": uom,
            "unit_price": round(random.uniform(min_p, max_p), 2),  # nosec B311
            "delivery_date": required_date,
        })

    return {
        "required_date": required_date,
        "purpose": random.choice(purposes),  # nosec B311
        "department": dept_cc["department"],
        "cost_center": dept_cc["cost_center"],
        "line_items": line_items,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MODE 2: EVENT SCANNER — creates Purchase Receipts and Invoices
# Triggered every 5 minutes by EventBridge
# ═══════════════════════════════════════════════════════════════════════════════


def tick_scan_receipts() -> dict:
    """Scan for POs needing Purchase Receipts only. Does NOT create invoices."""
    return _scan_receipts_only()


def tick_scan_invoices() -> dict:
    """Scan for POs needing Invoices only. Does NOT create receipts."""
    return _scan_invoices_only()


def tick_scan() -> dict:
    """Scan ERPNext for POs needing the next human action.

    Runs BOTH receipt and invoice scans. Use tick_scan_receipts() or
    tick_scan_invoices() for controlled single-action ticks.
    """
    receipt_result = _scan_receipts_only()
    invoice_result = _scan_invoices_only()
    return {
        "mode": "scan",
        "receipts_created": receipt_result.get("receipts_created", 0),
        "invoices_generated": invoice_result.get("invoices_generated", 0),
        "pos_scanned": receipt_result.get("pos_scanned", 0) + invoice_result.get("pos_scanned", 0),
        "errors": receipt_result.get("errors", 0) + invoice_result.get("errors", 0),
    }


def _scan_receipts_only() -> dict:
    """Create Purchase Receipts for POs awaiting goods delivery."""
    summary = {
        "mode": "scan_receipts",
        "receipts_created": 0,
        "invoices_generated": 0,
        "pos_scanned": 0,
        "errors": 0,
    }

    api = _get_api_client()
    now = datetime.now()

    # ── POs needing Purchase Receipts ───────────────────────────────────────
    try:
        pos_to_receive = _get_pos_needing_receipt(api)
        summary["pos_scanned"] += len(pos_to_receive)

        for po in pos_to_receive:
            try:
                order_id = po.get("order_id", "")
                order_date_str = po.get("order_date", "")

                # Check shipping delay: enough time must have passed since PO creation
                # Skip delay check in demo mode (both min and max are 0-1)
                if order_date_str and MAX_SHIPPING_DELAY_HOURS > 1:
                    order_date = _parse_date(order_date_str)
                    delay_hours = random.randint(MIN_SHIPPING_DELAY_HOURS, MAX_SHIPPING_DELAY_HOURS)  # nosec B311
                    earliest_receipt = order_date + timedelta(hours=delay_hours)
                    if now < earliest_receipt:
                        logger.debug("PO %s: too early for receipt (wait until %s)", order_id, earliest_receipt)
                        continue

                # Decide delivery pattern for this PO:
                # 40% chance: multiple partial deliveries (2-3 GRs in one tick)
                # 10% chance: single over-delivery (105-115% of qty)
                # 50% chance: single complete delivery
                roll = random.random()  # nosec B311
                if roll < 0.40:
                    num_shipments = random.randint(2, 3)  # nosec B311
                    delivery_mode = "multi_partial"
                elif roll < 0.50:
                    num_shipments = 1
                    delivery_mode = "over_delivery"
                else:
                    num_shipments = 1
                    delivery_mode = "complete"

                logger.info("PO %s: delivery mode=%s, shipments=%d", order_id, delivery_mode, num_shipments)

                for shipment_num in range(num_shipments):
                    # Re-fetch PO each time to get updated received quantities
                    po_detail = api.get_purchase_order(order_id)
                    receipt_data = _build_receipt_from_po(
                        po_detail,
                        delivery_mode=delivery_mode,
                        shipment_num=shipment_num,
                        total_shipments=num_shipments,
                    )
                    if receipt_data is None:
                        logger.info("PO %s: nothing left to receive after shipment %d", order_id, shipment_num)
                        break
                    result = api.create_receipt(receipt_data)
                    receipt_id = result.get("receipt_id", "")
                    logger.info("Created Purchase Receipt %s for PO %s (shipment %d/%d)",
                                receipt_id, order_id, shipment_num + 1, num_shipments)
                    summary["receipts_created"] += 1

            except Exception as e:
                logger.warning("Failed to create receipt for PO %s: %s", po.get("order_id", "?"), e)
                summary["errors"] += 1

    except Exception as e:
        logger.warning("Receipt scan failed: %s", e)
        summary["errors"] += 1

    logger.info("Receipt scan complete: %s", summary)
    return summary


def _scan_invoices_only() -> dict:
    """Create Invoices for POs that have been received but not yet billed."""
    summary = {
        "mode": "scan_invoices",
        "receipts_created": 0,
        "invoices_generated": 0,
        "pos_scanned": 0,
        "errors": 0,
    }

    api = _get_api_client()
    now = datetime.now()

    try:
        pos_to_bill = _get_pos_needing_invoice(api)
        summary["pos_scanned"] += len(pos_to_bill)

        for po in pos_to_bill:
            try:
                order_id = po.get("order_id", "")

                # Check billing delay: enough time since the receipt
                # Skip delay check in demo mode (both min and max are 0-1)
                order_date_str = po.get("order_date", "")
                if order_date_str and MAX_BILLING_DELAY_HOURS > 1:
                    order_date = _parse_date(order_date_str)
                    delay_hours = random.randint(MIN_BILLING_DELAY_HOURS, MAX_BILLING_DELAY_HOURS)  # nosec B311
                    earliest_invoice = order_date + timedelta(hours=delay_hours)
                    if now < earliest_invoice:
                        logger.debug("PO %s: too early for invoice (wait until %s)", order_id, earliest_invoice)
                        continue

                po_detail = api.get_purchase_order(order_id)

                # Generate invoice data for remaining unbilled items
                if USE_LLM:
                    try:
                        from .llm_generator import generate_invoice_data
                        scenario = random.choice(["clean", "clean", "clean", "price_variance"])  # nosec B311
                        invoice_data = generate_invoice_data(po_detail, scenario_type=scenario)
                    except Exception:
                        invoice_data = _template_invoice(po_detail)
                else:
                    invoice_data = _template_invoice(po_detail)

                if invoice_data is None:
                    logger.info("PO %s: nothing left to bill, skipping", order_id)
                    continue

                # Create the invoice as an electronic record in ERPNext
                result = api.create_invoice(invoice_data)
                inv_id = result.get("invoice_id", "")
                logger.info("Created invoice %s for PO %s", inv_id, order_id)
                summary["invoices_generated"] += 1

            except Exception as e:
                logger.warning("Failed to create invoice for PO %s: %s", po.get("order_id", "?"), e)
                summary["errors"] += 1

    except Exception as e:
        logger.warning("Invoice scan failed: %s", e)
        summary["errors"] += 1

    logger.info("Invoice scan complete: %s", summary)
    return summary


def _get_pos_needing_receipt(api: CanonicalAPIClient) -> list[dict]:
    """Find POs that still have items awaiting delivery.

    Returns POs with status to_receive — these may already have partial
    receipts but still have remaining quantities. The build function
    will calculate the remaining qty from the PO detail.
    """
    result = api._request("GET", "/purchase-orders?status=to_receive")
    po_list = result.get("purchase_orders", [])
    if not po_list:
        result = api._request("GET", "/purchase-orders?status=ordered")
        po_list = result.get("purchase_orders", [])
    # POs with to_receive status inherently need more goods — ERPNext only
    # moves to to_bill once ALL items are fully received. No extra filtering needed.
    return po_list[:3]


def _get_pos_needing_invoice(api: CanonicalAPIClient) -> list[dict]:
    """Find POs that have been received but not yet fully billed.

    Returns POs with to_bill status — ERPNext only moves to completed
    when 100% billed. The _template_invoice function checks billed_quantity
    per item and only invoices what's remaining (returns None if fully billed).
    """
    result = api._request("GET", "/purchase-orders?status=to_bill")
    po_list = result.get("purchase_orders", [])
    if not po_list:
        result = api._request("GET", "/purchase-orders?status=received")
        po_list = result.get("purchase_orders", [])
    return po_list[:2]


def _build_receipt_from_po(
    po: dict,
    delivery_mode: str = "complete",
    shipment_num: int = 0,
    total_shipments: int = 1,
) -> dict | None:
    """Build a Purchase Receipt from a PO based on REMAINING quantities.

    Delivery modes:
    - "complete": deliver all remaining items in full
    - "multi_partial": split delivery across multiple shipments
    - "over_delivery": deliver 105-115% of remaining (tests over-delivery handling)

    Returns None if nothing left to receive.
    """
    line_items = []
    for i, li in enumerate(po.get("line_items", [])):
        ordered_qty = li.get("quantity", 0)
        already_received = li.get("received_quantity", 0) or 0
        remaining = ordered_qty - already_received

        if remaining <= 0:
            continue  # fully received, skip this item

        if delivery_mode == "multi_partial":
            # Split remaining across shipments. Earlier shipments get ~40-60% of remaining.
            if shipment_num < total_shipments - 1:
                pct = random.uniform(0.3, 0.6)  # nosec B311
                deliver_qty = max(1, int(remaining * pct))
            else:
                deliver_qty = remaining  # last shipment gets everything left
        elif delivery_mode == "over_delivery":
            # Deliver 105-115% (triggers over-delivery detection in receiving agent)
            over_pct = random.uniform(1.05, 1.15)  # nosec B311
            deliver_qty = max(1, int(remaining * over_pct))
        else:
            # Complete delivery
            deliver_qty = remaining

        line_items.append({
            "line_number": i + 1,
            "item_id": li.get("item_id", ""),
            "quantity_received": deliver_qty,
            "unit_of_measure": li.get("unit_of_measure", "Nos"),
        })

    if not line_items:
        return None

    return {
        "order_id": po.get("order_id", ""),
        "supplier_id": po.get("supplier_id", po.get("supplier_name", "")),
        "line_items": line_items,
    }


def _template_invoice(po: dict) -> dict | None:
    """Generate a template invoice from a PO for REMAINING unbilled quantities.

    Checks each item's billed_quantity to only invoice what hasn't been billed yet.
    Returns None if nothing left to bill.
    """
    import uuid

    now = datetime.now()
    supplier_prefixes = {
        "Acme Industrial Supply": "ACME-INV",
        "Global Parts Co": "GPC",
        "Pacific Manufacturing": "PAC",
        "EuroTech Automation": "ET-DE",
        "Midwest Fasteners Inc": "MWF-INV",
        "SafetyFirst Equipment": "SFE",
    }
    supplier = po.get("supplier_name", "Unknown")
    prefix = supplier_prefixes.get(supplier, "INV")

    line_items = []
    for i, li in enumerate(po.get("line_items", [])):
        line_amount = li.get("line_amount", 0) or (li.get("quantity", 0) * li.get("unit_price", 0))
        already_billed = li.get("billed_amount", 0) or 0

        if already_billed >= line_amount and line_amount > 0:
            continue  # fully billed, skip

        qty = li.get("quantity", 0)
        price = li.get("unit_price", 0)
        line_items.append({
            "line_number": i + 1,
            "item_id": li.get("item_id", ""),
            "quantity": qty,
            "unit_price": price,
            "line_amount": round(qty * price, 2),
            "order_id": po.get("order_id", ""),
        })

    if not line_items:
        return None  # nothing left to bill

    return {
        "supplier_id": po.get("supplier_id", ""),
        "vendor_invoice_number": f"{prefix}-{now.strftime('%Y')}-{uuid.uuid4().hex[:4].upper()}",
        "invoice_date": now.strftime("%Y-%m-%d"),
        "due_date": (now + timedelta(days=30)).strftime("%Y-%m-%d"),
        "order_id": po.get("order_id", ""),
        "line_items": line_items,
    }


def _parse_date(date_str: str) -> datetime:
    """Parse an ISO date string to datetime. Handles both date-only and datetime."""
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+00:00", ""))
    except (ValueError, AttributeError):
        return datetime.now() - timedelta(days=7)  # Fallback: assume 7 days old


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY: Combined tick for backwards compatibility
# ═══════════════════════════════════════════════════════════════════════════════


def tick(force_pr_count: int | None = None) -> dict:
    """Combined tick — runs both demand + scan. Used for manual testing."""
    demand = tick_demand(force_pr_count=force_pr_count)
    scan = tick_scan()
    return {
        "material_requests_created": demand.get("material_requests_created", 0),
        "receipts_created": scan.get("receipts_created", 0),
        "invoices_generated": scan.get("invoices_generated", 0),
        "errors": demand.get("errors", 0) + scan.get("errors", 0),
    }
