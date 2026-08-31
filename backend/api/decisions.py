# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Decisions API — audit trail for agent runs, recommendations, and human decisions.

All entries are stored in the document-lifecycle table's `runs` array.
Supports tree structure: workflows contain nested step entries via parent_id.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services import erp_client
from services.auth import get_authenticated_user
from services.lifecycle import (
    add_run_entry, record_approval, record_rejection,
    resolve_pending_decision, list_lifecycles, get_lifecycle,
)

logger = logging.getLogger("p2p.api.decisions")

router = APIRouter()


class DecisionRequest(BaseModel):
    document_type: str          # "PR" or "INVOICE"
    document_id: str
    action: str                 # "APPROVE" or "REJECT"
    justification: str = ""
    agent_recommendation: str = ""
    agent_confidence: float = 0.0
    agent_reasoning: str = ""
    match_result: str = ""


@router.get("/")
def list_decisions():
    """List all run entries across all documents, most recent first.

    Returns top-level entries (workflows, standalone analyses, decisions)
    with their children available via the per-document endpoint.
    """
    lifecycles = list_lifecycles()
    all_entries = []

    for lc in lifecycles:
        doc_id = lc.get("document_id", "")
        doc_type = lc.get("document_type", "PR")

        runs = lc.get("runs", [])
        if isinstance(runs, str):
            try:
                runs = json.loads(runs)
            except (json.JSONDecodeError, TypeError):
                runs = []

        for r in runs:
            entry_type = r.get("type", "")
            parent_id = r.get("parent_id")

            # Include: workflow entries, ALL decision entries, and receiving agent standalone
            # invoice_matching and payment standalone analyses are read-only previews — excluded
            # They only appear as children of a payment_workflow
            is_downstream_analysis = (
                entry_type == "analysis"
                and not parent_id
                and r.get("agent", "") in ("receiving",)
            )
            if entry_type == "workflow" or entry_type == "decision" or is_downstream_analysis:
                all_entries.append({
                    "decision_id": r.get("id", ""),
                    "document_type": doc_type,
                    "document_id": doc_id,
                    "type": entry_type,
                    "agent": r.get("agent", ""),
                    "action": r.get("action") or r.get("recommendation") or "",
                    "status": r.get("status", ""),
                    "decided_by": r.get("decided_by") or ("AI_AGENT" if entry_type != "decision" else ""),
                    "decided_at": r.get("completed_at") or r.get("started_at") or "",
                    "recommendation": r.get("recommendation", ""),
                    "confidence": r.get("confidence", 0),
                    "summary": r.get("summary", ""),
                    "justification": r.get("justification", ""),
                    "parent_id": parent_id or "",
                    # For backward compat with existing frontend
                    "agent_recommendation": r.get("recommendation") or r.get("action") or "",
                    "agent_confidence": str(r.get("confidence", 0) or 0),
                    "agent_reasoning": r.get("summary", ""),
                })

        # Also include legacy decisions[] entries for backward compat
        decisions = lc.get("decisions", [])
        if isinstance(decisions, str):
            try:
                decisions = json.loads(decisions)
            except (json.JSONDecodeError, TypeError):
                decisions = []

        # Only include legacy decisions if no runs[] exist (migration period)
        if not runs and decisions:
            for d in decisions:
                all_entries.append({
                    "decision_id": d.get("id", ""),
                    "document_type": doc_type,
                    "document_id": doc_id,
                    "type": "decision",
                    "agent": "",
                    "action": d.get("action", ""),
                    "status": "completed",
                    "decided_by": d.get("decided_by", ""),
                    "decided_at": d.get("decided_at", ""),
                    "recommendation": d.get("action", ""),
                    "confidence": d.get("confidence", 0),
                    "summary": "",
                    "justification": d.get("justification", ""),
                    "parent_id": "",
                    "agent_recommendation": d.get("action", ""),
                    "agent_confidence": str(d.get("confidence", 0)),
                    "agent_reasoning": "",
                })

    all_entries.sort(key=lambda x: x.get("decided_at", ""), reverse=True)
    return json.loads(json.dumps(all_entries, default=str))


@router.get("/{document_id}/runs")
def get_document_runs(document_id: str):
    """Get all run entries for a specific document.

    Returns the full runs array — frontend builds tree from parent_id.
    """
    lc = get_lifecycle(document_id)
    if not lc:
        return {"document_id": document_id, "runs": []}

    runs = lc.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            runs = []

    return json.loads(json.dumps({"document_id": document_id, "runs": runs}, default=str))


@router.post("/")
def record_decision(body: DecisionRequest, request: Request):
    """Record a human approval or rejection decision."""
    from services.auth import get_user_email
    auth_user = get_authenticated_user(request)
    user_email = get_user_email(request)
    decided_by = user_email or auth_user or "unknown"

    # Map to canonical action names: HUMAN_APPROVED / HUMAN_REJECTED
    canonical_action = "HUMAN_APPROVED" if body.action == "APPROVE" else "HUMAN_REJECTED"

    # Update the existing AI_ESCALATED entry in-place (no duplicate)
    resolved = resolve_pending_decision(
        document_id=body.document_id,
        action=canonical_action,
        decided_by=decided_by,
        justification=body.justification,
    )
    if not resolved:
        # No pending decision found — create a new entry (standalone approval)
        add_run_entry(
            document_id=body.document_id,
            entry_type="decision",
            action=canonical_action,
            decided_by=decided_by,
            status="approved" if body.action == "APPROVE" else "rejected",
            justification=body.justification,
            confidence=body.agent_confidence,
            summary=f"Human {body.action.lower()}: {body.justification[:100]}" if body.justification else f"Human {body.action.lower()}",
        )

    # Update lifecycle status
    if body.action == "APPROVE":
        record_approval(body.document_id, approved_by=decided_by)
    elif body.action == "REJECT":
        record_rejection(body.document_id, rejected_by=decided_by)

    logger.info("Decision: %s %s %s by %s", body.action, body.document_type, body.document_id, decided_by)

    # ERPNext status update for invoice overrides
    if body.document_type == "INVOICE" and body.action == "APPROVE":
        _try_update_invoice_status(body.document_id, user_email=user_email)

    # Stop MR in ERPNext when a human rejects a purchase requisition
    if body.document_type == "PR" and body.action == "REJECT":
        _try_stop_material_request(body.document_id, user_email=user_email)

    return {
        "document_id": body.document_id,
        "action": body.action,
        "decided_by": decided_by,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


def _try_stop_material_request(mr_id: str, user_email: Optional[str] = None) -> None:
    """Stop the Material Request in ERPNext when a human rejects it."""
    try:
        if not erp_client.is_configured():
            return
        resp = erp_client.request(
            "POST", f"/requisitions/{mr_id}/stop", user_email=user_email, timeout=10,
        )
        if resp.ok:
            logger.info("Material Request %s stopped in ERPNext", mr_id)
        else:
            logger.warning("Failed to stop MR %s: HTTP %s", mr_id, resp.status_code)
    except Exception as e:
        logger.warning("Failed to stop ERPNext MR %s: %s", mr_id, e)


def _try_update_invoice_status(invoice_id: str, user_email: Optional[str] = None) -> None:
    """Update invoice status in ERPNext on override approval."""
    try:
        if not erp_client.is_configured():
            return
        resp = erp_client.request(
            "POST", f"/invoices/{invoice_id}/submit", user_email=user_email, timeout=10,
        )
        if resp.ok:
            logger.info("Invoice %s submitted in ERPNext", invoice_id)
    except Exception as e:
        logger.warning("Failed to update ERPNext for invoice %s: %s", invoice_id, e)
