# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Workflows API — stub.

Workflow state now lives in ERPNext document status.
Agent coordination is tracked in DynamoDB document-lifecycle table.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_workflows():
    """Stub — workflow state is derived from ERP document status."""
    return {"items": [], "total": 0}
