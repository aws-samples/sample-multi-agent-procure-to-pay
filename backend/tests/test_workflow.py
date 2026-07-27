# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Tests for the workflow state machine in workflow/orchestrator.py.

Uses moto DynamoDB via fixtures.
"""

import pytest
import boto3
from moto import mock_aws

from workflow.orchestrator import (
    WorkflowState,
    StepStatus,
    STEP_AGENTS,
    create_workflow,
    get_workflow,
    list_workflows,
    advance_workflow,
    fail_workflow,
    resume_workflow,
    reject_workflow,
    _make_steps,
)


@pytest.fixture
def dynamo():
    """Moto DynamoDB with the agent-jobs table."""
    import os
    prefix = os.environ.get("DYNAMODB_TABLE_PREFIX", "p2p-test")
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=f"{prefix}-agent-jobs",
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # Point the dynamo service at moto
        import services.dynamo as svc
        svc.dynamodb = dynamodb
        yield dynamodb


class TestCreateWorkflow:
    def test_creates_with_correct_state(self, dynamo):
        wf = create_workflow("MAT-REQ-001", "sarah.johnson")
        assert wf["state"] == WorkflowState.CREATED.value
        assert wf["document_id"] == "MAT-REQ-001"
        assert wf["created_by"] == "sarah.johnson"
        assert wf["job_id"]
        assert wf["workflow_id"]

    def test_creates_with_three_steps(self, dynamo):
        wf = create_workflow("MAT-REQ-002", "test")
        import json
        steps = json.loads(wf["steps"]) if isinstance(wf["steps"], str) else wf["steps"]
        assert len(steps) == 3
        agent_names = [s["agent"] for s in steps]
        assert agent_names == STEP_AGENTS


class TestGetWorkflow:
    def test_retrieves_created_workflow(self, dynamo):
        wf = create_workflow("MAT-REQ-003", "test")
        retrieved = get_workflow(wf["job_id"])
        assert retrieved is not None
        assert retrieved["document_id"] == "MAT-REQ-003"

    def test_returns_none_for_missing(self, dynamo):
        result = get_workflow("nonexistent-id")
        assert result is None


class TestListWorkflows:
    def test_lists_all_workflows(self, dynamo):
        create_workflow("MAT-REQ-A", "test")
        create_workflow("MAT-REQ-B", "test")
        wfs = list_workflows()
        assert len(wfs) == 2

    def test_filters_by_state(self, dynamo):
        create_workflow("MAT-REQ-C", "test")
        wfs = list_workflows(state=WorkflowState.CREATED.value)
        assert len(wfs) == 1
        assert wfs[0]["state"] == WorkflowState.CREATED.value

    def test_filter_returns_empty(self, dynamo):
        create_workflow("MAT-REQ-D", "test")
        wfs = list_workflows(state=WorkflowState.COMPLETED.value)
        assert len(wfs) == 0


class TestAdvanceWorkflow:
    def test_advances_from_created(self, dynamo):
        wf = create_workflow("MAT-REQ-E", "test")
        advanced = advance_workflow(wf["job_id"])
        assert advanced["state"] == WorkflowState.ANALYZING.value

    def test_advance_missing_returns_stub(self, dynamo):
        result = advance_workflow("nonexistent")
        assert result["state"] == WorkflowState.ANALYZING.value


class TestResumeReject:
    def test_resume_moves_to_sourcing(self, dynamo):
        wf = create_workflow("MAT-REQ-F", "test")
        # Manually set to PENDING_APPROVAL
        import services.dynamo as svc
        svc.update_item("agent-jobs", {"job_id": wf["job_id"]},
                        {"state": WorkflowState.PENDING_APPROVAL.value})
        resumed = resume_workflow(wf["job_id"], "approver")
        assert resumed["state"] == WorkflowState.SOURCING.value

    def test_reject_marks_failed(self, dynamo):
        wf = create_workflow("MAT-REQ-G", "test")
        rejected = reject_workflow(wf["job_id"], "approver")
        assert rejected["state"] == WorkflowState.FAILED.value
        assert "Rejected by approver" in rejected.get("error", "")


class TestFailWorkflow:
    def test_fail_sets_error(self, dynamo):
        wf = create_workflow("MAT-REQ-H", "test")
        failed = fail_workflow(wf["job_id"], "Agent crashed")
        assert failed["state"] == WorkflowState.FAILED.value
        assert failed["error"] == "Agent crashed"

    def test_fail_missing_returns_stub(self, dynamo):
        result = fail_workflow("nonexistent", "error msg")
        assert result["state"] == "FAILED"


class TestMakeSteps:
    def test_step_count(self):
        steps = _make_steps()
        assert len(steps) == 3

    def test_step_agents(self):
        steps = _make_steps()
        agents = [s["agent"] for s in steps]
        assert agents == ["requisition", "sourcing", "po_management"]

    def test_initial_status(self):
        steps = _make_steps()
        for step in steps:
            assert step["status"] == StepStatus.PENDING.value
