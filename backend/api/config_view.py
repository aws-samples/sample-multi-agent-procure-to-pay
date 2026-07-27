# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Configuration view: approval rules, agent prompts, contracts, delegations."""

import json
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.auth import get_authenticated_user
from services.dynamo import put_item, scan_table

logger = logging.getLogger("p2p.api.config")

router = APIRouter()


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@router.get("/rules")
def get_approval_rules():
    """Return the current approval rules (hard limits enforced by Cedar Policy Engine)."""
    return {
        "enforcement": "Cedar Policy Engine (ENFORCE mode)",
        "hard_limits": {
            "requisition_max_amount": 50000,
            "purchase_order_max_amount": 50000,
            "payment_max_amount": 50000,
            "note": "Amounts above these thresholds require admin role. Enforced at Gateway level via Cedar policies.",
        },
        "agent_rules": {
            "requisition": {
                "auto_approve_threshold": 5000,
                "escalation_threshold": 50000,
                "duplicate_window_days": 30,
                "price_variance_low_pct": 10,
                "price_variance_medium_pct": 25,
            },
            "invoice_matching": {
                "price_tolerance_pct": 3,
                "quantity_tolerance_pct": 0,
                "auto_approve_confidence": 0.9,
                "allow_partial_invoices": True,
                "partial_invoice_min_match_pct": 80,
                "max_amount_tolerance": 50,
            },
            "sourcing": {
                "weights": {"price": 35, "delivery": 30, "quality": 20, "capacity": 15},
                "min_score_for_recommendation": 50,
                "tie_break_preference": "delivery",
            },
        },
    }


# ---------------------------------------------------------------------------
# Agent configs
# ---------------------------------------------------------------------------

@router.get("/agents")
def get_agent_configs():
    """Return each agent's objective and system prompt."""
    agents = []

    agent_info = [
        {
            "name": "Requisition Agent",
            "id": "requisition",
            "objective": "Validates purchase requisitions, checks for duplicates, compares pricing against historical data, and recommends approval, rejection, or escalation.",
            "decisions": "APPROVE (auto if LOW risk and under threshold), ESCALATE (HIGH risk or over threshold), REJECT (invalid data or policy violation)",
        },
        {
            "name": "Sourcing Agent",
            "id": "sourcing",
            "objective": "Evaluates all qualified vendors for a requisition based on price history, delivery performance, quality, and capacity. Recommends the optimal vendor.",
            "decisions": "Vendor recommendation with weighted scoring (Price 35%, Delivery 30%, Quality 20%, Capacity 15%)",
        },
        {
            "name": "PO Management Agent",
            "id": "po_management",
            "objective": "Generates purchase orders from approved requisitions. Validates materials, applies pricing and terms, checks for consolidation opportunities with existing POs.",
            "decisions": "CREATE (new PO), CONSOLIDATE (add to existing PO), ESCALATE (validation issues)",
        },
        {
            "name": "Receiving Agent",
            "id": "receiving",
            "objective": "Validates goods receipts against purchase orders. Checks quantities, flags over/under deliveries, tracks partial receipts, and evaluates delivery timing.",
            "decisions": "ACCEPTED, PARTIAL (partial delivery), OVER_DELIVERY, ESCALATE",
        },
        {
            "name": "Invoice Matching Agent",
            "id": "invoice_matching",
            "objective": "Performs three-way matching: compares invoice line items against the purchase order and goods receipt. Identifies price and quantity variances.",
            "decisions": "MATCHED (all items within tolerance), DISCREPANCY (variance found), ESCALATE (missing data or major issues)",
        },
        {
            "name": "Payment Agent",
            "id": "payment",
            "objective": "Analyzes payment timing to optimize for early payment discounts. Evaluates payment terms, calculates annualized discount rates, and recommends payment scheduling.",
            "decisions": "PAY_NOW, PAY_AT_DISCOUNT (take early payment discount), PAY_AT_DUE (wait for due date), HOLD",
        },
    ]

    prompt_modules = {
        "requisition": "agents.requisition_agent",
        "sourcing": "agents.sourcing_agent",
        "po_management": "agents.po_management_agent",
        "receiving": "agents.receiving_agent",
        "invoice_matching": "agents.invoice_matching_agent",
        "payment": "agents.payment_agent",
    }

    for info in agent_info:
        try:
            import importlib
            # nosemgrep -- non-literal-import: intentional lazy/dynamic import to avoid heavy import at module load
            mod = importlib.import_module(prompt_modules[info["id"]])
            info["system_prompt"] = getattr(mod, "SYSTEM_PROMPT", "Not available")
        except Exception:
            info["system_prompt"] = "Could not load prompt"
        agents.append(info)

    return agents


# ---------------------------------------------------------------------------
# Contracts (demo data)
# ---------------------------------------------------------------------------

@router.get("/contracts")
def get_contracts():
    """Return framework agreements and blanket POs.

    Sourced from services.contracts — the same data the Sourcing and PO
    Management agents read, so the Configuration view and the agents never
    disagree about which contracts exist.
    """
    from services.contracts import list_contracts

    return list_contracts()


# ---------------------------------------------------------------------------
# Delegations
# ---------------------------------------------------------------------------

class DelegationCreate(BaseModel):
    delegate_to: str
    start_date: str
    end_date: str
    spend_limit: float = 0
    notes: str = ""


@router.get("/delegations")
def list_delegations():
    """List all approval delegations (stored in lifecycle table with delegation- prefix)."""
    try:
        from services.lifecycle import list_lifecycles
        all_items = list_lifecycles()
        delegations = [i for i in all_items if str(i.get("document_id", "")).startswith("delegation-")]
        delegations.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return json.loads(json.dumps(delegations, default=str))
    except Exception:
        return []


@router.post("/delegations")
def create_delegation(body: DelegationCreate, request: Request):
    """Create a new approval delegation."""
    from services.dynamo import put_item as ddb_put
    auth_user = get_authenticated_user(request) or "unknown"

    record = {
        "document_id": f"delegation-{uuid.uuid4()}",
        "document_type": "DELEGATION",
        "status": "active",
        "delegate_from": auth_user,
        "delegate_to": body.delegate_to,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "spend_limit": str(body.spend_limit),
        "notes": body.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    ddb_put("document-lifecycle", record)
    logger.info("Delegation created: %s → %s", auth_user, body.delegate_to)
    return json.loads(json.dumps(record, default=str))
