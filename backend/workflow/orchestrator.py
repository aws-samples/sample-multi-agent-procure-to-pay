# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Workflow Orchestrator — simplified.

Workflow state tracking is handled by the document-lifecycle DDB table.
This module now only provides the WorkflowState enum for backward compatibility
and the chat session create/advance helpers used by the chat agent.

All workflow state transitions (SOURCING → SOURCING_COMPLETE → ANALYZING → PENDING_APPROVAL → PO_CREATED)
happen through services/lifecycle.py typed helpers.
"""

import logging
from enum import Enum

logger = logging.getLogger("p2p.workflow")


class WorkflowState(str, Enum):
    """Kept for backward compatibility with any code that references it."""
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    SOURCING = "SOURCING"
    PO_GENERATION = "PO_GENERATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def create_workflow(document_id: str, created_by: str, **kwargs) -> dict:
    """Create a workflow by initializing the lifecycle record.

    Returns a stub dict for backward compatibility.
    """
    from services.lifecycle import set_status, Status
    set_status(document_id, Status.CREATED)
    return {"document_id": document_id, "created_by": created_by}


def list_workflows(**kwargs) -> list[dict]:
    """List workflows from lifecycle table."""
    from services.lifecycle import list_lifecycles
    return list_lifecycles()
