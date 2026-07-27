# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Tests for the AgentCore Runtime entrypoint in agentcore_app.py.

All tests mock external dependencies (boto3, data_provider, agent modules).
"""

import importlib
import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: reload agentcore_app with controlled env vars
# ---------------------------------------------------------------------------

def _import_agentcore(**env_overrides):
    """Import (or reimport) agentcore_app with specified env overrides.

    This is needed because GUARDRAIL_ID is read at module scope.
    We also stub out BedrockAgentCoreApp so it does not connect to anything.
    """
    old_env = {}
    for k, v in env_overrides.items():
        old_env[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    # Stub the runtime SDK so import does not fail without AWS credentials
    fake_runtime = types.ModuleType("bedrock_agentcore.runtime")
    fake_runtime.BedrockAgentCoreApp = lambda: MagicMock()
    sys.modules["bedrock_agentcore"] = types.ModuleType("bedrock_agentcore")
    sys.modules["bedrock_agentcore.runtime"] = fake_runtime

    # Stub strands modules so agent classes are available but don't call AWS
    if "strands" not in sys.modules:
        fake_strands = types.ModuleType("strands")
        fake_strands.Agent = MagicMock
        fake_strands.tool = lambda fn: fn
        sys.modules["strands"] = fake_strands
    if "strands.models" not in sys.modules:
        fake_models = types.ModuleType("strands.models")
        fake_models.BedrockModel = MagicMock
        sys.modules["strands.models"] = fake_models

    try:
        if "agentcore_app" in sys.modules:
            mod = importlib.reload(sys.modules["agentcore_app"])
        else:
            mod = importlib.import_module("agentcore_app")
        return mod
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Module-level import for tests that don't need env manipulation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ac():
    """Return the agentcore_app module with an empty guardrail ID."""
    return _import_agentcore(BEDROCK_GUARDRAIL_ID="", GATEWAY_ENDPOINT="")


# ===========================================================================
# AGENT_LABELS coverage
# ===========================================================================

class TestAgentLabels:
    EXPECTED_AGENTS = [
        "requisition", "sourcing", "po_management",
        "receiving", "invoice_matching", "payment",
    ]

    def test_all_six_agents_present(self, ac):
        for name in self.EXPECTED_AGENTS:
            assert name in ac.AGENT_LABELS, f"{name} missing from AGENT_LABELS"

    def test_labels_are_nonempty_strings(self, ac):
        for name, label in ac.AGENT_LABELS.items():
            assert isinstance(label, str) and len(label) > 0


# ===========================================================================
# TOOL_DESCRIPTIONS coverage
# ===========================================================================

class TestToolDescriptions:
    EXPECTED_MCP_TOOLS = [
        "erp__list_suppliers",
        "erp__get_supplier",
        "erp__list_items",
        "erp__get_item",
        "erp__list_requisitions",
        "erp__get_requisition",
        "erp__create_requisition",
        "erp__list_purchase_orders",
        "erp__get_purchase_order",
        "erp__create_purchase_order",
        "erp__list_receipts",
        "erp__get_receipt",
        "erp__list_invoices",
        "erp__get_invoice",
        "erp__create_invoice",
        "erp__list_payments",
        "erp__create_payment",
        "erp__get_spend_summary",
        "erp__get_supplier_performance",
        "erp__extract_invoice_document",
    ]

    EXPECTED_LOCAL_TOOLS = [
        "check_budget",
        "get_framework_agreements",
        "get_blanket_pos",
    ]

    def test_mcp_tool_names_present(self, ac):
        for tool_name in self.EXPECTED_MCP_TOOLS:
            assert tool_name in ac.TOOL_DESCRIPTIONS, f"{tool_name} missing from TOOL_DESCRIPTIONS"

    def test_local_tool_names_present(self, ac):
        for tool_name in self.EXPECTED_LOCAL_TOOLS:
            assert tool_name in ac.TOOL_DESCRIPTIONS, f"{tool_name} missing from TOOL_DESCRIPTIONS"

    def test_descriptions_are_nonempty(self, ac):
        for name, desc in ac.TOOL_DESCRIPTIONS.items():
            assert isinstance(desc, str) and len(desc) > 0, f"{name} has empty description"


# ===========================================================================
# _get_system_prompt tests
# ===========================================================================

class TestGetSystemPrompt:
    AGENT_NAMES = [
        "requisition", "sourcing", "po_management",
        "receiving", "invoice_matching", "payment",
    ]

    def test_returns_nonempty_for_all_agents(self, ac):
        for name in self.AGENT_NAMES:
            prompt = ac._get_system_prompt(name)
            assert isinstance(prompt, str), f"{name}: expected str, got {type(prompt)}"
            assert len(prompt) > 50, f"{name}: prompt too short ({len(prompt)} chars)"

    def test_returns_empty_for_unknown_agent(self, ac):
        prompt = ac._get_system_prompt("nonexistent_agent")
        assert prompt == ""


# ===========================================================================
# _build_local_tools tests
# ===========================================================================

class TestBuildLocalTools:
    def test_requisition_includes_budget_tool(self, ac):
        tools = ac._build_local_tools("requisition")
        assert len(tools) >= 1
        # The budget tool is a strands @tool-decorated function named check_budget
        tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
        assert any("budget" in n.lower() for n in tool_names), f"No budget tool found in {tool_names}"

    def test_sourcing_includes_contract_tools(self, ac):
        tools = ac._build_local_tools("sourcing")
        assert len(tools) >= 2
        tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
        name_str = " ".join(tool_names).lower()
        assert "agreement" in name_str or "framework" in name_str or "contract" in name_str or "blanket" in name_str, \
            f"No contract tools found in {tool_names}"

    def test_po_management_includes_contract_tools(self, ac):
        tools = ac._build_local_tools("po_management")
        assert len(tools) >= 1

    def test_payment_returns_empty(self, ac):
        tools = ac._build_local_tools("payment")
        assert tools == []

    def test_receiving_returns_empty(self, ac):
        tools = ac._build_local_tools("receiving")
        assert tools == []

    def test_unknown_agent_returns_empty(self, ac):
        tools = ac._build_local_tools("nonexistent")
        assert tools == []


# ===========================================================================
# _post_process tests
# ===========================================================================

class TestPostProcess:
    """Tests for the deterministic post-processing rules."""

    def test_auto_approve_low_risk_small_amount(self, ac):
        parsed = {"risk_level": "LOW", "total_amount": 3000, "recommendation": "APPROVE", "auto_approved": False}
        result = ac._post_process("requisition", parsed)
        assert result["auto_approved"] is True
        assert result["recommendation"] == "APPROVE"

    def test_escalate_high_risk(self, ac):
        parsed = {"risk_level": "HIGH", "total_amount": 1000, "recommendation": "APPROVE", "auto_approved": True}
        result = ac._post_process("requisition", parsed)
        assert result["auto_approved"] is False
        assert result["recommendation"] == "ESCALATE"

    def test_escalate_large_amount(self, ac):
        parsed = {"risk_level": "MEDIUM", "total_amount": 60000, "recommendation": "APPROVE", "auto_approved": True}
        result = ac._post_process("requisition", parsed)
        assert result["auto_approved"] is False
        assert result["recommendation"] == "ESCALATE"

    def test_budget_fail_escalates(self, ac):
        parsed = {
            "risk_level": "LOW", "total_amount": 2000, "recommendation": "APPROVE",
            "auto_approved": True,
            "findings": [{"check": "Budget impact", "status": "FAIL", "detail": "Over budget"}],
        }
        result = ac._post_process("requisition", parsed)
        assert result["risk_level"] == "HIGH"
        assert result["auto_approved"] is False
        assert result["recommendation"] == "ESCALATE"

    def test_non_requisition_passthrough(self, ac):
        parsed = {"match_result": "MATCHED", "confidence": 0.95}
        result = ac._post_process("invoice_matching", parsed)
        assert result == parsed


# ===========================================================================
# _get_prompt tests
# ===========================================================================

class TestGetPrompt:
    AGENT_NAMES = [
        "requisition", "sourcing", "po_management",
        "receiving", "invoice_matching", "payment",
    ]

    def test_returns_prompt_containing_document_id(self, ac):
        for name in self.AGENT_NAMES:
            prompt = ac._get_prompt(name, "DOC-999")
            assert "DOC-999" in prompt, f"{name}: prompt does not contain document_id"

    def test_unknown_agent_returns_fallback(self, ac):
        prompt = ac._get_prompt("unknown_agent", "DOC-001")
        assert "DOC-001" in prompt


# ===========================================================================
# _validate_with_guardrail tests
# ===========================================================================

class TestValidateWithGuardrail:

    def test_skips_when_guardrail_id_empty(self):
        """When BEDROCK_GUARDRAIL_ID is empty, validation is skipped."""
        mod = _import_agentcore(BEDROCK_GUARDRAIL_ID="")
        result = mod._validate_with_guardrail("some agent output")
        assert result["valid"] is True
        assert result["action"] == "NONE"
        assert result["findings"] == []

    def test_returns_valid_true_when_action_none(self):
        """When guardrail returns action=NONE, result is valid."""
        mod = _import_agentcore(BEDROCK_GUARDRAIL_ID="gr-test-123")

        mock_response = {
            "action": "NONE",
            "assessments": [],
        }
        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = mock_response

        with patch("boto3.client", return_value=mock_client):
            result = mod._validate_with_guardrail("safe output text")

        assert result["valid"] is True
        assert result["action"] == "NONE"
        assert result["findings"] == []

    def test_returns_valid_false_when_intervened(self):
        """When guardrail intervenes, valid=False and findings are populated."""
        mod = _import_agentcore(BEDROCK_GUARDRAIL_ID="gr-test-456")

        mock_response = {
            "action": "GUARDRAIL_INTERVENED",
            "assessments": [
                {
                    "automatedReasoningPolicy": {
                        "findings": [
                            {
                                "result": "VIOLATION",
                                "rule": "max-approval-amount",
                                "explanation": "Amount exceeds single-approver limit of $50,000",
                            }
                        ]
                    }
                }
            ],
        }
        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = mock_response

        with patch("boto3.client", return_value=mock_client):
            result = mod._validate_with_guardrail("approve $100,000 purchase")

        assert result["valid"] is False
        assert result["action"] == "GUARDRAIL_INTERVENED"
        assert len(result["findings"]) == 1
        assert result["findings"][0]["result"] == "VIOLATION"
        assert result["findings"][0]["rule"] == "max-approval-amount"

    def test_handles_boto3_error_gracefully(self):
        """When boto3 raises an exception, validation returns valid=True with error info."""
        mod = _import_agentcore(BEDROCK_GUARDRAIL_ID="gr-test-789")

        mock_client = MagicMock()
        mock_client.apply_guardrail.side_effect = Exception("Service unavailable")

        with patch("boto3.client", return_value=mock_client):
            result = mod._validate_with_guardrail("some output")

        assert result["valid"] is True
        assert result["action"] == "ERROR"
        assert "Service unavailable" in result.get("error", "")

    def test_multiple_findings_extracted(self):
        """Multiple AR findings from a single assessment are all captured."""
        mod = _import_agentcore(BEDROCK_GUARDRAIL_ID="gr-multi")

        mock_response = {
            "action": "GUARDRAIL_INTERVENED",
            "assessments": [
                {
                    "automatedReasoningPolicy": {
                        "findings": [
                            {"result": "VIOLATION", "rule": "rule-1", "explanation": "First violation"},
                            {"result": "WARNING", "rule": "rule-2", "explanation": "Second issue"},
                        ]
                    }
                }
            ],
        }
        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = mock_response

        with patch("boto3.client", return_value=mock_client):
            result = mod._validate_with_guardrail("risky text")

        assert len(result["findings"]) == 2
        assert result["findings"][0]["rule"] == "rule-1"
        assert result["findings"][1]["rule"] == "rule-2"

    def test_empty_assessments_returns_valid(self):
        """When guardrail returns NONE with empty assessments, result is valid."""
        mod = _import_agentcore(BEDROCK_GUARDRAIL_ID="gr-empty")

        mock_response = {"action": "NONE", "assessments": []}
        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = mock_response

        with patch("boto3.client", return_value=mock_client):
            result = mod._validate_with_guardrail("clean output")

        assert result["valid"] is True
        assert result["findings"] == []
