# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Item 1: Agent behavior tests with mocked Bedrock responses.

Tests agent tool building, input validation, error handling,
and response parsing without calling Bedrock.
"""

import pytest


class TestRequisitionAgent:
    def test_system_prompt_is_nonempty(self):
        from agents.requisition_agent import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 50

    def test_build_budget_tool(self):
        from agents.requisition_agent import build_budget_tool
        tool = build_budget_tool()
        assert callable(tool)
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        assert "budget" in name.lower()


class TestInvoiceMatchingAgent:
    def test_system_prompt_built_correctly(self):
        from agents.invoice_matching_agent import _build_system_prompt
        prompt = _build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 50
        assert "three-way" in prompt.lower() or "3-way" in prompt.lower() or "three way" in prompt.lower()


class TestSourcingAgent:
    def test_system_prompt_built_correctly(self):
        from agents.sourcing_agent import _build_system_prompt
        prompt = _build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_build_contract_tools(self):
        from agents.sourcing_agent import build_contract_tools
        tools = build_contract_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 2


class TestPaymentAgent:
    def test_system_prompt_is_nonempty(self):
        from agents.payment_agent import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 50


class TestReceivingAgent:
    def test_system_prompt_is_nonempty(self):
        from agents.receiving_agent import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 50


class TestChatAgent:
    def test_build_local_tools(self):
        from agents.chat_agent import _build_local_tools
        tools = _build_local_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 1
        tool_names = [getattr(t, "name", getattr(t, "__name__", "")) for t in tools]
        assert any("workflow" in n.lower() for n in tool_names)

    def test_invoke_exists(self):
        from agents.chat_agent import invoke
        assert callable(invoke)


class TestApprovalRules:
    """Approval rules are now baked into system prompts and enforced by Cedar policies."""

    def test_rules_in_config_api(self):
        from api.config_view import get_approval_rules
        rules = get_approval_rules()
        assert "hard_limits" in rules
        assert rules["hard_limits"]["requisition_max_amount"] == 50000

    def test_requisition_prompt_has_thresholds(self):
        from agents.requisition_agent import SYSTEM_PROMPT
        assert "$5,000" in SYSTEM_PROMPT
        assert "$50,000" in SYSTEM_PROMPT



class TestExceptions:
    def test_classify_throttle(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("ThrottlingException: Rate exceeded"), "test")
        assert cat == ErrorCategory.BEDROCK_THROTTLED

    def test_classify_timeout(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Connection timed out"), "test")
        assert cat == ErrorCategory.AGENT_TIMEOUT

    def test_classify_not_found(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Document not found"), "test")
        assert cat == ErrorCategory.DOCUMENT_NOT_FOUND

    def test_create_agent_error(self):
        from services.exceptions import create_agent_error
        error = create_agent_error(
            Exception("Test error"),
            "test_agent",
            "DOC001",
            "PR",
        )
        assert error.agent_name == "test_agent"
        assert error.document_id == "DOC001"
        assert error.error_id is not None
