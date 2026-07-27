# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Verify all agent prompts use canonical naming (no SAP field names)."""

import pytest
import os
import sys
import importlib

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SAP_FIELDS_IN_PROMPTS = ["BANFN", "EBELN", "BELNR", "LIFNR", "MATNR", "MBLNR"]

AGENT_MODULES = [
    "agents.requisition_agent",
    "agents.sourcing_agent",
    "agents.po_management_agent",
    "agents.receiving_agent",
    "agents.invoice_matching_agent",
    "agents.payment_agent",
]


class TestAgentImports:
    """All agent modules import without errors."""

    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_agent_imports(self, module_name):
        # nosemgrep -- non-literal-import: intentional lazy/dynamic import to avoid heavy import at module load
        mod = importlib.import_module(module_name)
        assert hasattr(mod, "SYSTEM_PROMPT"), f"{module_name} missing SYSTEM_PROMPT"

    def test_chat_agent_imports(self):
        mod = importlib.import_module("agents.chat_agent")
        assert hasattr(mod, "invoke")

    def test_workflow_imports(self):
        mod = importlib.import_module("agents.p2p_workflow")
        assert hasattr(mod, "_extract_text")
        assert hasattr(mod, "_parse_json")


class TestNoSAPFieldsInPrompts:
    """No SAP field names should appear in agent system prompts."""

    @pytest.mark.parametrize("module_name", AGENT_MODULES)
    def test_no_sap_fields_in_system_prompt(self, module_name):
        # nosemgrep -- non-literal-import: intentional lazy/dynamic import to avoid heavy import at module load
        mod = importlib.import_module(module_name)
        prompt = getattr(mod, "SYSTEM_PROMPT", None)
        if prompt is None:
            pytest.skip(f"{module_name} has no SYSTEM_PROMPT")
        for field in SAP_FIELDS_IN_PROMPTS:
            assert field not in prompt, (
                f"{module_name} SYSTEM_PROMPT still contains SAP field '{field}'"
            )


class TestNoSAPFieldsInPromptFStrings:
    """No SAP fields in f-string prompts used by agentcore_app or workflow."""

    def test_workflow_prompts(self):
        """Check p2p_workflow.py for SAP fields in prompt strings."""
        path = os.path.join(os.path.dirname(__file__), "..", "agents", "p2p_workflow.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for field in SAP_FIELDS_IN_PROMPTS:
            # Check for SAP field in f-string context (e.g., f"...BANFN=...")
            if f'{field}=' in content:
                lines = [l.strip() for l in content.split('\n')
                         if f'{field}=' in l and ('f"' in l or "f'" in l)]
                assert not lines, (
                    f"p2p_workflow.py has SAP field '{field}' in prompt f-strings: {lines}"
                )


class TestLocalToolBuilders:
    """Agents that still have local tool builders should work correctly."""

    def test_requisition_budget_tool(self):
        from agents.requisition_agent import build_budget_tool
        tool = build_budget_tool()
        assert callable(tool)
        name = getattr(tool, "name", getattr(tool, "__name__", ""))
        assert "budget" in name.lower()

    def test_sourcing_contract_tools(self):
        from agents.sourcing_agent import build_contract_tools
        tools = build_contract_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 2

    def test_po_management_contract_tools(self):
        from agents.po_management_agent import build_contract_tools
        tools = build_contract_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 1
