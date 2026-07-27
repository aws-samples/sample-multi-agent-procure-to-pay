# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Tests for Cedar policy files — structural validation.

Validates that the Cedar policy file covers the expected P2P authorization
rules: role-based access control via permit-only policies.
Dollar limits are enforced at the application layer (_post_process + human approval).
"""

import os
import re

import pytest

POLICY_DIR = os.path.join(os.path.dirname(__file__), "..", "policies")
POLICY_FILE = os.path.join(POLICY_DIR, "p2p-procurement.cedar")


@pytest.fixture
def policy_text():
    with open(POLICY_FILE, encoding="utf-8") as f:
        return f.read()


class TestPolicyStructure:
    def test_has_permit_statements(self, policy_text):
        permits = re.findall(r"^permit\(", policy_text, re.MULTILINE)
        assert len(permits) == 6, f"Expected 6 permit statements, found {len(permits)}"

    def test_no_forbid_statements(self, policy_text):
        forbids = re.findall(r"^forbid\(", policy_text, re.MULTILINE)
        assert len(forbids) == 0

    def test_uses_correct_principal_types(self, policy_text):
        assert "AgentCore::OAuthUser" in policy_text
        assert "AgentCore::IamEntity" in policy_text


class TestRoleCoverage:
    def test_all_roles_present(self, policy_text):
        for role in ["requester", "procurement", "ap_clerk", "approver", "admin"]:
            assert f'"{role}"' in policy_text, f"Role {role} missing"

    def test_admin_has_broad_write(self, policy_text):
        assert policy_text.count('"admin"') >= 4


class TestReadToolCoverage:
    READ_TOOLS = [
        "list_suppliers", "get_supplier", "list_items", "get_item",
        "list_requisitions", "get_requisition", "list_purchase_orders",
        "get_purchase_order", "list_receipts", "get_receipt",
        "list_invoices", "get_invoice", "list_payments",
        "get_spend_summary", "get_supplier_performance",
    ]

    @pytest.mark.parametrize("tool", READ_TOOLS)
    def test_read_tool_in_policy(self, tool, policy_text):
        assert f'erp___{tool}' in policy_text


class TestWriteToolCoverage:
    WRITE_TOOLS = ["create_requisition", "create_purchase_order",
                   "create_receipt", "create_invoice", "create_payment"]

    @pytest.mark.parametrize("tool", WRITE_TOOLS)
    def test_write_tool_has_role_check(self, tool, policy_text):
        oauth = policy_text[policy_text.index("AgentCore::OAuthUser"):]
        assert f'erp___{tool}' in oauth
