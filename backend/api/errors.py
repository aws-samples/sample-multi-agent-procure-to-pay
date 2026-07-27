# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Error management API — view, resolve, and retry agent failures.
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException
from services.dynamo import get_item, scan_table, update_item, put_item
from services.exceptions import AgentError

router = APIRouter()


@router.get("/")
def list_errors(resolved: bool = False, agent: str = None):
    """List agent errors, optionally filtered by resolution status or agent."""
    errors = scan_table("agent-errors")
    if not resolved:
        errors = [e for e in errors if not e.get("resolved", False)]
    if agent:
        errors = [e for e in errors if e.get("agent_name") == agent]
    # Sort by timestamp descending
    errors.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return errors


@router.get("/{error_id}")
def get_error(error_id: str):
    """Get a specific error by ID."""
    error = get_item("agent-errors", {"error_id": error_id})
    if not error:
        raise HTTPException(status_code=404, detail="Error not found")
    return error


@router.post("/{error_id}/resolve")
def resolve_error(error_id: str, resolved_by: str = "manual"):
    """Mark an error as resolved."""
    return update_item(
        "agent-errors",
        {"error_id": error_id},
        {
            "resolved": True,
            "resolved_by": resolved_by,
            "resolved_at": datetime.utcnow().isoformat(),
        },
    )


@router.post("/{error_id}/retry")
def retry_error(error_id: str):
    """Retry a failed agent operation. Returns the error with updated retry count."""
    error = get_item("agent-errors", {"error_id": error_id})
    if not error:
        raise HTTPException(status_code=404, detail="Error not found")
    if not error.get("retry_eligible", False):
        raise HTTPException(status_code=400, detail="This error is not eligible for retry")
    if error.get("retries_attempted", 0) >= error.get("max_retries", 3):
        raise HTTPException(status_code=400, detail="Max retries exceeded")

    # Increment retry count
    update_item(
        "agent-errors",
        {"error_id": error_id},
        {"retries_attempted": error.get("retries_attempted", 0) + 1},
    )

    return {
        "status": "retry_queued",
        "error_id": error_id,
        "document_id": error.get("document_id"),
        "agent_name": error.get("agent_name"),
        "message": "Retry has been queued. Re-run the agent from the appropriate page to process this document again.",
    }


@router.get("/summary/counts")
def error_summary():
    """Dashboard summary — error counts by category and severity."""
    errors = scan_table("agent-errors")
    unresolved = [e for e in errors if not e.get("resolved", False)]

    by_severity = {}
    by_category = {}
    by_agent = {}
    human_action_needed = 0

    for e in unresolved:
        sev = e.get("severity", "UNKNOWN")
        cat = e.get("category", "UNKNOWN")
        agent = e.get("agent_name", "unknown")

        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_category[cat] = by_category.get(cat, 0) + 1
        by_agent[agent] = by_agent.get(agent, 0) + 1
        if e.get("human_action_required"):
            human_action_needed += 1

    return {
        "total_unresolved": len(unresolved),
        "human_action_needed": human_action_needed,
        "by_severity": by_severity,
        "by_category": by_category,
        "by_agent": by_agent,
    }
