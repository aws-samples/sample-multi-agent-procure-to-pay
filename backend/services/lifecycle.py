# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Document Lifecycle Tracking — normalized schema.

One DDB record per document_id, tracking the full procurement lifecycle.
All fields are NORMALIZED (fixed names, explicit types) — never raw agent JSON.

Status progression (MR):
  CREATED → SOURCING → SOURCING_COMPLETE → ANALYZING → [approval gate]
    ├─ AUTO-APPROVE: → PO_GENERATION → PO_CREATED
    ├─ DEFER TO HUMAN: → PENDING_APPROVAL → APPROVED → PO_GENERATION → PO_CREATED
    └─ AUTO-REJECT: → REJECTED (after Step 2, both sourcing and analysis complete)

Terminal: REJECTED, FAILED

Run tracking:
  All agent runs, workflow executions, and decisions are tracked in a unified
  `runs` array with parent_id linkage for tree structure.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from services.dynamo import put_item, get_item, scan_table

logger = logging.getLogger("p2p.lifecycle")

TABLE_NAME = "document-lifecycle"


class Status(str, Enum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SOURCING = "SOURCING"
    SOURCING_COMPLETE = "SOURCING_COMPLETE"
    PO_GENERATION = "PO_GENERATION"
    PO_CREATED = "PO_CREATED"
    # Invoice flow
    MATCHING = "MATCHING"
    MATCH_COMPLETE = "MATCH_COMPLETE"
    PENDING_REVIEW = "PENDING_REVIEW"
    PAYMENT_SCHEDULED = "PAYMENT_SCHEDULED"
    PAID = "PAID"
    # Terminal
    REJECTED = "REJECTED"
    FAILED = "FAILED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(val) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def _serialize(record: dict) -> dict:
    """Prepare record for DDB — convert floats to Decimal, lists to JSON strings."""
    out = {}
    for k, v in record.items():
        if v is None:
            continue
        if isinstance(v, float):
            out[k] = Decimal(str(v))
        elif isinstance(v, list):
            out[k] = json.dumps(v, default=str)
        elif isinstance(v, dict):
            out[k] = json.dumps(v, default=str)
        else:
            out[k] = v
    return out


def _deserialize(record: dict) -> dict:
    """Restore record from DDB — convert Decimals to float, JSON strings to objects."""
    if not record:
        return record
    out = {}
    for k, v in record.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif k in ("analysis_findings", "decisions", "analysis_runs", "runs", "po_order_ids") and isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                out[k] = v
        else:
            out[k] = v
    return out


# ─── Core CRUD ──────────────────────────────────────────────────────────────


def get_lifecycle(document_id: str) -> Optional[dict]:
    """Get lifecycle record. Returns None if not found."""
    try:
        item = get_item(TABLE_NAME, {"document_id": document_id})
        return _deserialize(item) if item else None
    except Exception as e:
        logger.warning("get_lifecycle(%s) failed: %s", document_id, e)
        return None


def get_lifecycle_by_po(order_id: str) -> Optional[dict]:
    """Find the lifecycle record whose po_order_id matches.

    Used by downstream agents (receiving, invoice matching, payment)
    to find the MR lifecycle record for a given PO.

    Note: Table scan — fine for demo scale. Add GSI on po_order_id for production.
    """
    try:
        items = scan_table(TABLE_NAME)
        for item in items:
            deserialized = _deserialize(item)
            if deserialized.get("po_order_id") == order_id:
                return deserialized
        return None
    except Exception as e:
        logger.warning("get_lifecycle_by_po(%s) failed: %s", order_id, e)
        return None


def _upsert(document_id: str, updates: dict) -> dict:
    """Internal: merge updates into existing record (or create new)."""
    record = get_lifecycle(document_id) or {
        "document_id": document_id,
        "document_type": "PR",
        "status": Status.CREATED.value,
        "created_at": _now(),
        "decisions": [],
        "analysis_runs": [],
        "runs": [],
    }
    record.update(updates)
    record["updated_at"] = _now()
    try:
        put_item(TABLE_NAME, _serialize(record))
    except Exception as e:
        logger.warning("_upsert(%s) failed: %s", document_id, e)
    return record


def list_lifecycles(status: Optional[str] = None) -> list[dict]:
    """List all lifecycle records, optionally filtered by status."""
    try:
        items = scan_table(TABLE_NAME)
        if status:
            items = [i for i in items if i.get("status") == status]
        items = [_deserialize(i) for i in items]
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return json.loads(json.dumps(items, default=str))
    except Exception as e:
        logger.warning("list_lifecycles failed: %s", e)
        return []


# ─── Typed Step Helpers (normalize agent output) ────────────────────────────


def set_status(document_id: str, status: Status, current_step: str = "") -> dict:
    """Update lifecycle status and current_step."""
    updates = {"status": status.value}
    if current_step:
        updates["current_step"] = current_step
    return _upsert(document_id, updates)


def record_po_created(
    document_id: str,
    order_id: str,
    total_amount: float = 0,
    action: str = "CREATE",
    order_ids: list[str] | None = None,
) -> dict:
    """Record Step 3 results — PO(s) created in ERPNext.

    Supports split awards via order_ids (list of PO IDs).
    order_id is the primary PO; order_ids stores all POs for split awards.
    """
    updates = {
        "status": Status.PO_CREATED.value if order_id else Status.FAILED.value,
        "current_step": "complete",
        "po_action": action,
        "po_order_id": order_id,
        "po_total_amount": total_amount,
        "po_completed_at": _now(),
        "erp_order_id": order_id,
    }
    if order_ids and len(order_ids) > 1:
        updates["po_order_ids"] = order_ids
    return _upsert(document_id, updates)


def record_approval(document_id: str, approved_by: str) -> dict:
    """Record human approval."""
    return _upsert(document_id, {
        "status": Status.APPROVED.value,
        "approved_by": approved_by,
        "approved_at": _now(),
    })


def record_rejection(document_id: str, rejected_by: str) -> dict:
    """Record human rejection."""
    return _upsert(document_id, {
        "status": Status.REJECTED.value,
        "rejected_by": rejected_by,
        "rejected_at": _now(),
    })


def record_failure(document_id: str, error: str) -> dict:
    """Record agent failure."""
    return _upsert(document_id, {
        "status": Status.FAILED.value,
        "error": error[:2000],
    })


# ─── Unified Run Tracking ─────────────────────────────────────────────────


def add_run_entry(
    document_id: str,
    entry_type: str,
    agent: str = "",
    parent_id: str = "",
    status: str = "completed",
    recommendation: str = "",
    confidence: float = 0.0,
    summary: str = "",
    result: dict = None,
    action: str = "",
    decided_by: str = "",
    justification: str = "",
) -> str:
    """Append a run entry to the lifecycle's unified `runs` array.

    This is the ONLY place step results are stored — no duplication at top level.

    Args:
        document_id: The document being processed.
        entry_type: "workflow" | "analysis" | "decision".
        agent: Agent name (workflow, requisition, sourcing, po_management).
        parent_id: Links to parent workflow run ID ("" for top-level).
        status: running, completed, failed, pending_approval, approved, rejected.
        recommendation: Agent recommendation (APPROVE, REJECT, ESCALATE, vendor name).
        confidence: 0.0-1.0.
        summary: Full reasoning/summary text (not truncated).
        result: Full agent result dict (findings, reasoning, vendor details, etc.).
        action: Decision action (AI_APPROVED, HUMAN_REJECTED, etc.).
        decided_by: Who decided (email, AI_AGENT).
        justification: Reason for decision.

    Returns:
        The generated run entry ID (UUID string).
    """
    run_id = str(uuid.uuid4())

    record = get_lifecycle(document_id) or {
        "document_id": document_id,
        "document_type": "PR",
        "status": Status.CREATED.value,
        "created_at": _now(),
        "runs": [],
    }

    runs = record.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            runs = []

    entry = {
        "id": run_id,
        "parent_id": parent_id or None,
        "type": entry_type,
        "agent": agent,
        "status": status,
        "started_at": _now(),
        "completed_at": _now() if status != "running" else None,
        "recommendation": recommendation or None,
        "confidence": _safe_float(confidence) if confidence else None,
        "summary": summary or None,
        "result": result if result else None,
        "action": action or None,
        "decided_by": decided_by or None,
        "justification": justification or None,
    }
    # Strip None values to keep DDB records lean
    entry = {k: v for k, v in entry.items() if v is not None}
    runs.append(entry)

    record["runs"] = runs
    record["updated_at"] = _now()

    try:
        put_item(TABLE_NAME, _serialize(record))
    except Exception as e:
        logger.warning("add_run_entry(%s) failed: %s", document_id, e)

    return run_id


def update_run_status(document_id: str, run_id: str, status: str) -> None:
    """Update the status of a specific run entry in the runs array."""
    record = get_lifecycle(document_id)
    if not record:
        return

    runs = record.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            return

    for entry in runs:
        if entry.get("id") == run_id:
            entry["status"] = status
            if status not in ("running",):
                entry["completed_at"] = _now()
            break

    record["runs"] = runs
    record["updated_at"] = _now()

    try:
        put_item(TABLE_NAME, _serialize(record))
    except Exception as e:
        logger.warning("update_run_status(%s, %s) failed: %s", document_id, run_id, e)


def resolve_pending_decision(
    document_id: str,
    action: str,
    decided_by: str,
    justification: str = "",
) -> bool:
    """Update the latest AI_ESCALATED decision entry with the human's resolution.

    Instead of creating a duplicate decision entry, this finds the pending
    AI_ESCALATED entry and updates it in-place with the human's action.

    Returns True if a pending entry was found and updated, False otherwise.
    """
    record = get_lifecycle(document_id)
    if not record:
        return False

    runs = record.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            return False

    # Find the latest pending_approval decision (AI_ESCALATED)
    target = None
    for entry in reversed(runs):
        if entry.get("type") == "decision" and entry.get("status") == "pending_approval":
            target = entry
            break

    if not target:
        return False

    # Update in-place: human resolves the AI's escalation
    target["action"] = action
    target["decided_by"] = decided_by
    target["status"] = "approved" if "APPROVED" in action else "rejected"
    target["completed_at"] = _now()
    if justification:
        target["justification"] = (target.get("justification", "") + f" | {decided_by}: {justification}").strip(" |")

    record["runs"] = runs
    record["updated_at"] = _now()

    # Also update top-level lifecycle status in the same write to avoid
    # race conditions with eventual consistency on the follow-up _upsert.
    if "APPROVED" in action:
        record["status"] = Status.APPROVED.value
        record["approved_by"] = decided_by
        record["approved_at"] = _now()
    else:
        record["status"] = Status.REJECTED.value
        record["rejected_by"] = decided_by
        record["rejected_at"] = _now()

    # Also update the parent workflow run entry status
    for entry in runs:
        if entry.get("type") == "workflow" and entry.get("status") == "pending_approval":
            entry["status"] = "approved" if "APPROVED" in action else "rejected"
            entry["completed_at"] = _now()
            break

    try:
        put_item(TABLE_NAME, _serialize(record))
        logger.info("resolve_pending_decision(%s): %s by %s", document_id, action, decided_by)
        return True
    except Exception as e:
        logger.warning("resolve_pending_decision(%s) failed: %s", document_id, e)
        return False


def is_workflow_active(document_id: str, stale_minutes: int = 10) -> dict:
    """Check if a workflow is currently running for this document.

    Returns dict with: active, stale, run_id, status, started_at, current_step.
    A workflow is active if the lifecycle status is in an intermediate running state
    AND there's a workflow run entry with status="running" in runs[].
    If the run started more than stale_minutes ago, it's considered stale (crashed).
    """
    ACTIVE_STATUSES = {
        Status.CREATED.value, Status.SOURCING.value, Status.SOURCING_COMPLETE.value,
        Status.ANALYZING.value, Status.PO_GENERATION.value, Status.MATCHING.value,
    }
    result = {"active": False, "stale": False, "run_id": "", "status": "", "started_at": "", "current_step": ""}

    record = get_lifecycle(document_id)
    if not record:
        return result

    status = record.get("status", "")
    if status not in ACTIVE_STATUSES:
        return result

    result["status"] = status
    result["current_step"] = record.get("current_step", "")

    runs = record.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            # Status says active but runs can't be parsed — treat as stale
            result["active"] = True
            result["stale"] = True
            return result

    # Find the latest workflow run entry with "running" status
    for entry in reversed(runs):
        if entry.get("type") == "workflow" and entry.get("status") == "running":
            result["active"] = True
            result["run_id"] = entry.get("id", "")
            result["started_at"] = entry.get("started_at", "")

            # Check staleness
            started_at = entry.get("started_at", "")
            if started_at:
                try:
                    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                    result["stale"] = elapsed > (stale_minutes * 60)
                except (ValueError, TypeError):
                    result["stale"] = True
            else:
                result["stale"] = True
            return result

    # Status is in a running state but no "running" workflow entry — orphaned/stale
    result["active"] = True
    result["stale"] = True
    return result


def is_agent_active(document_id: str, agent_name: str, stale_minutes: int = 5) -> dict:
    """Check if a standalone agent is currently running for this document.

    Checks runs[] for an entry with agent=agent_name and status="running".
    Returns dict with: active, stale, run_id, started_at.
    """
    result = {"active": False, "stale": False, "run_id": "", "started_at": ""}

    record = get_lifecycle(document_id)
    if not record:
        return result

    runs = record.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            return result

    for entry in reversed(runs):
        if entry.get("agent") == agent_name and entry.get("status") == "running":
            result["active"] = True
            result["run_id"] = entry.get("id", "")
            result["started_at"] = entry.get("started_at", "")

            started_at = entry.get("started_at", "")
            if started_at:
                try:
                    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                    result["stale"] = elapsed > (stale_minutes * 60)
                except (ValueError, TypeError):
                    result["stale"] = True
            else:
                result["stale"] = True
            return result

    return result


def update_run_entry(
    document_id: str,
    run_id: str,
    status: str = "completed",
    recommendation: str = "",
    confidence: float = 0.0,
    summary: str = "",
    result: dict = None,
) -> None:
    """Update an existing run entry with completion data."""
    record = get_lifecycle(document_id)
    if not record:
        return

    runs = record.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            return

    for entry in runs:
        if entry.get("id") == run_id:
            entry["status"] = status
            entry["completed_at"] = _now()
            if recommendation:
                entry["recommendation"] = recommendation
            if confidence:
                entry["confidence"] = _safe_float(confidence)
            if summary:
                entry["summary"] = summary
            if result:
                entry["result"] = result
            break

    record["runs"] = runs
    record["updated_at"] = _now()

    try:
        put_item(TABLE_NAME, _serialize(record))
    except Exception as e:
        logger.warning("update_run_entry(%s, %s) failed: %s", document_id, run_id, e)


def get_latest_workflow_run_id(document_id: str) -> str:
    """Find the most recent workflow run ID for a document (for resume)."""
    record = get_lifecycle(document_id)
    if not record:
        return ""

    runs = record.get("runs", [])
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except (json.JSONDecodeError, TypeError):
            return ""

    # Find latest workflow entry (reverse search)
    for entry in reversed(runs):
        if entry.get("type") == "workflow":
            return entry.get("id", "")
    return ""
