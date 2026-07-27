# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Tests for main.py FastAPI routes.

Tests the route modules mounted on the operational API:
  agents, decisions, errors, config_view, dashboard, admin.

Uses the app_client fixture from conftest.py (moto-backed DynamoDB).
"""

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(username: str = "test.user") -> dict:
    """Return headers that auth.get_authenticated_user() will resolve to *username*."""
    return {"x-amz-user": username}


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_ok(self, app_client):
        resp = app_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 1. Agents routes (/api/agents/*)
# ---------------------------------------------------------------------------

class TestAgentRoutes:
    """Tests for api/agents.py -- chat + streaming proxy + rate-limit."""

    def test_rate_limit_status(self, app_client):
        resp = app_client.get("/api/agents/rate-limit")
        assert resp.status_code == 200
        body = resp.json()
        assert "used" in body
        assert "limit" in body
        assert "remaining" in body
        assert "window_seconds" in body

    @patch("agents.chat_agent.invoke")
    def test_agent_chat(self, mock_chat_invoke, app_client):
        mock_chat_invoke.return_value = {"reply": "Hello from chat agent"}
        resp = app_client.post(
            "/api/agents/chat",
            json={"message": "What PRs need approval?", "role": "admin"},
        )
        assert resp.status_code == 200
        mock_chat_invoke.assert_called_once()

    def test_stream_agent_no_arn(self, app_client):
        """When AgentCore ARN is not configured, return error JSON."""
        resp = app_client.post(
            "/api/agents/unknown_agent/stream",
            params={"document_id": "PR-001"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body

    def test_stream_agent_no_bearer(self, app_client):
        """When no bearer token, return error even if ARN exists."""
        with patch("api.agents._get_agentcore_arn", return_value="arn:aws:fake"):
            resp = app_client.post(
                "/api/agents/requisition/stream",
                params={"document_id": "PR-001"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert "bearer" in body["error"].lower() or "token" in body["error"].lower()


# ---------------------------------------------------------------------------
# 2. Decisions routes (/api/decisions/*)
# ---------------------------------------------------------------------------

class TestDecisionRoutes:
    """Tests for api/decisions.py -- audit trail listing and recording."""

    def test_list_decisions_empty(self, app_client):
        resp = app_client.get("/api/decisions/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 0

    def test_list_decisions_after_recording(self, app_client):
        """Record a decision through POST /api/decisions/, then verify it appears."""
        app_client.post(
            "/api/decisions/",
            json={
                "document_type": "PR",
                "document_id": "MAT-REQ-AUDIT-001",
                "action": "APPROVE",
                "justification": "Test approval",
            },
            headers=_auth_headers("sarah.johnson"),
        )
        resp = app_client.get("/api/decisions/")
        assert resp.status_code == 200
        decisions = resp.json()
        assert len(decisions) >= 1
        assert any(d["document_id"] == "MAT-REQ-AUDIT-001" for d in decisions)


class TestDecisionRecording:
    """Tests for POST /api/decisions/ -- human approval/rejection."""

    def test_record_decision_approve(self, app_client):
        resp = app_client.post(
            "/api/decisions/",
            json={
                "document_type": "PR",
                "document_id": "MAT-REQ-00001",
                "action": "APPROVE",
                "justification": "Looks good",
                "agent_recommendation": "ESCALATE",
                "agent_confidence": 0.75,
                "agent_reasoning": "Over threshold",
            },
            headers=_auth_headers("sarah.johnson"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "APPROVE"
        assert body["document_type"] == "PR"
        assert body["document_id"] == "MAT-REQ-00001"
        assert body["decided_by"] == "sarah.johnson"
        assert body["justification"] == "Looks good"
        assert "decision_id" in body

    def test_record_decision_reject(self, app_client):
        resp = app_client.post(
            "/api/decisions/",
            json={
                "document_type": "INVOICE",
                "document_id": "ACC-PINV-2025-00001",
                "action": "REJECT",
                "justification": "Price mismatch too large",
                "match_result": "DISCREPANCY",
                "agent_confidence": 0.6,
            },
            headers=_auth_headers("sarah.johnson"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "REJECT"
        assert body["document_type"] == "INVOICE"

    def test_record_decision_appears_in_list(self, app_client):
        app_client.post(
            "/api/decisions/",
            json={
                "document_type": "PR",
                "document_id": "MAT-REQ-AUDIT-TEST",
                "action": "APPROVE",
            },
            headers=_auth_headers("sarah.johnson"),
        )
        resp = app_client.get("/api/decisions/")
        assert resp.status_code == 200
        items = resp.json()
        found = [d for d in items if d.get("document_id") == "MAT-REQ-AUDIT-TEST"]
        assert len(found) >= 1
        assert found[0]["action"] == "APPROVE"


# ---------------------------------------------------------------------------
# 3. Errors routes (/api/errors/*)
# ---------------------------------------------------------------------------

class TestErrorRoutes:
    """Tests for api/errors.py -- error tracking, resolution, retry."""

    def _seed_error(self, app_client, error_id=None, retry_eligible=False, resolved=False):
        from services.dynamo import put_item
        eid = error_id or str(uuid.uuid4())
        put_item("agent-errors", {
            "error_id": eid,
            "agent_name": "requisition",
            "document_id": "PR-001",
            "error_type": "AnalysisError",
            "message": "Mock error",
            "severity": "HIGH",
            "category": "AGENT_FAILURE",
            "timestamp": "2026-04-09T10:00:00",
            "resolved": resolved,
            "retry_eligible": retry_eligible,
            "retries_attempted": 0,
            "max_retries": 3,
            "human_action_required": True,
        })
        return eid

    def test_list_errors_empty(self, app_client):
        resp = app_client.get("/api/errors/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_errors_filters_resolved(self, app_client):
        eid = self._seed_error(app_client, resolved=True)
        resp = app_client.get("/api/errors/")
        ids = [e["error_id"] for e in resp.json()]
        assert eid not in ids

        resp = app_client.get("/api/errors/", params={"resolved": "true"})
        ids = [e["error_id"] for e in resp.json()]
        assert eid in ids

    def test_get_error_by_id(self, app_client):
        eid = self._seed_error(app_client)
        resp = app_client.get(f"/api/errors/{eid}")
        assert resp.status_code == 200
        assert resp.json()["error_id"] == eid

    def test_get_error_not_found(self, app_client):
        resp = app_client.get("/api/errors/nonexistent-id")
        assert resp.status_code == 404

    def test_resolve_error(self, app_client):
        eid = self._seed_error(app_client)
        resp = app_client.post(f"/api/errors/{eid}/resolve", params={"resolved_by": "admin"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["resolved"] is True
        assert body["resolved_by"] == "admin"

    def test_retry_error_success(self, app_client):
        eid = self._seed_error(app_client, retry_eligible=True)
        resp = app_client.post(f"/api/errors/{eid}/retry")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "retry_queued"

    def test_retry_error_not_eligible(self, app_client):
        eid = self._seed_error(app_client, retry_eligible=False)
        resp = app_client.post(f"/api/errors/{eid}/retry")
        assert resp.status_code == 400

    def test_retry_error_not_found(self, app_client):
        resp = app_client.post("/api/errors/nonexistent-id/retry")
        assert resp.status_code == 404

    def test_error_summary_counts(self, app_client):
        self._seed_error(app_client)
        resp = app_client.get("/api/errors/summary/counts")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_unresolved" in body
        assert "human_action_needed" in body
        assert body["total_unresolved"] >= 1


# ---------------------------------------------------------------------------
# 4. Config View routes (/api/config/*)
# ---------------------------------------------------------------------------

class TestConfigViewRoutes:
    """Tests for api/config_view.py -- read-only config endpoints."""

    def test_get_approval_rules(self, app_client):
        resp = app_client.get("/api/config/rules")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert "hard_limits" in body
        assert "agent_rules" in body

    def test_get_agent_configs(self, app_client):
        resp = app_client.get("/api/config/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert isinstance(agents, list)
        assert len(agents) == 6
        agent_ids = [a["id"] for a in agents]
        assert "requisition" in agent_ids
        assert "sourcing" in agent_ids
        assert "payment" in agent_ids
        for agent in agents:
            assert "system_prompt" in agent


# ---------------------------------------------------------------------------
# 5. Dashboard routes (/api/dashboard/*)
# ---------------------------------------------------------------------------

class TestDashboardRoutes:
    """Tests for api/dashboard.py -- aggregated metrics."""

    def test_dashboard_metrics(self, app_client):
        resp = app_client.get("/api/dashboard/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_spend" in body
        assert "total_orders" in body
        assert "currency" in body


# ---------------------------------------------------------------------------
# 6. Admin routes (/api/admin/*)
# ---------------------------------------------------------------------------

class TestAdminRoutes:
    """Tests for api/admin.py -- reset and status."""

    def test_admin_reset(self, app_client):
        resp = app_client.post("/api/admin/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "reset_complete"
        assert "counts" in body

    def test_admin_reset_clears_decisions(self, app_client):
        """Verify reset actually clears DynamoDB tables."""
        app_client.post(
            "/api/decisions/",
            json={
                "document_type": "PR",
                "document_id": "MAT-REQ-RESET-TEST",
                "action": "APPROVE",
            },
            headers=_auth_headers("sarah.johnson"),
        )
        resp = app_client.get("/api/decisions/")
        assert len(resp.json()) >= 1

        app_client.post("/api/admin/reset")

        resp = app_client.get("/api/decisions/")
        assert len(resp.json()) == 0

    def test_admin_status_no_adapter(self, app_client):
        """Without ADAPTER_API_URL, status returns error."""
        resp = app_client.get("/api/admin/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
