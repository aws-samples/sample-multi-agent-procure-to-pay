# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Document Lifecycle API — tracks MRs and Invoices through their full procurement lifecycle.

GET /lifecycle/{document_id} — get lifecycle record (used by frontend to restore state)
GET /lifecycle/ — list all lifecycle records (for Command Center)
"""

import logging
from typing import Optional
from fastapi import APIRouter, Query

from services.lifecycle import get_lifecycle, list_lifecycles

router = APIRouter()
logger = logging.getLogger("p2p.api.lifecycle")


@router.get("/{document_id}")
def get_document_lifecycle(document_id: str):
    """Get the lifecycle record for a specific document."""
    record = get_lifecycle(document_id)
    if not record:
        return {"document_id": document_id, "status": None}
    return record


@router.get("/")
def list_document_lifecycles(status: Optional[str] = Query(None)):
    """List all lifecycle records, optionally filtered by status."""
    return {"lifecycles": list_lifecycles(status=status)}
