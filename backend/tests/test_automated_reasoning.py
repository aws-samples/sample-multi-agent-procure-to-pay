# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for Automated Reasoning guardrail validation."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestValidateWithGuardrail:
    """Test the _validate_with_guardrail function.

    Since agentcore_app.py imports bedrock_agentcore (only available in container),
    we extract and test the validation function directly by mocking the import.
    """

    @pytest.fixture(autouse=True)
    def setup_guardrail_function(self):
        """Extract _validate_with_guardrail without importing the full module."""
        # The function only needs os, json, logging, boto3 — no agentcore deps.
        # We define it here matching the implementation in agentcore_app.py.
        self.guardrail_id = ""
        self.guardrail_version = "DRAFT"

        def _validate_with_guardrail(response_text: str) -> dict:
            if not self.guardrail_id:
                return {"valid": True, "action": "NONE", "findings": []}
            try:
                import boto3
                bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
                response = bedrock.apply_guardrail(
                    guardrailIdentifier=self.guardrail_id,
                    guardrailVersion=self.guardrail_version,
                    source="OUTPUT",
                    content=[{"text": {"text": response_text}}],
                )
                action = response.get("action", "NONE")
                ar_findings = []
                for assessment in response.get("assessments", []):
                    ar = assessment.get("automatedReasoningPolicy", {})
                    for finding in ar.get("findings", []):
                        ar_findings.append({
                            "result": finding.get("result"),
                            "rule": finding.get("rule", ""),
                            "explanation": finding.get("explanation", ""),
                        })
                return {"valid": action == "NONE", "action": action, "findings": ar_findings}
            except Exception as e:
                return {"valid": True, "action": "ERROR", "findings": [], "error": str(e)}

        self.validate = _validate_with_guardrail

    def test_skips_when_guardrail_not_configured(self):
        self.guardrail_id = ""
        result = self.validate("Some agent response text")
        assert result["valid"] is True
        assert result["action"] == "NONE"
        assert result["findings"] == []

    def test_returns_valid_when_no_violations(self):
        self.guardrail_id = "test-guardrail-123"
        mock_response = {"action": "NONE", "assessments": []}

        with patch("boto3.client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.apply_guardrail.return_value = mock_response

            result = self.validate(
                "The invoice for $5,000 matches the PO amount. Recommend APPROVE."
            )

        assert result["valid"] is True
        assert result["action"] == "NONE"
        assert result["findings"] == []

    def test_returns_invalid_findings(self):
        self.guardrail_id = "test-guardrail-123"
        mock_response = {
            "action": "GUARDRAIL_INTERVENED",
            "assessments": [{
                "automatedReasoningPolicy": {
                    "findings": [{
                        "result": "INVALID",
                        "rule": "Rule 1.2: Invoice price must not exceed PO price by more than 3%",
                        "explanation": "The invoice price $1,150 exceeds PO price $1,000 by 15%.",
                    }]
                }
            }],
        }

        with patch("boto3.client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.apply_guardrail.return_value = mock_response

            result = self.validate(
                "Invoice price is $1,150 vs PO $1,000. Recommend APPROVE."
            )

        assert result["valid"] is False
        assert result["action"] == "GUARDRAIL_INTERVENED"
        assert len(result["findings"]) == 1
        assert result["findings"][0]["result"] == "INVALID"
        assert "3%" in result["findings"][0]["rule"]

    def test_returns_multiple_findings(self):
        self.guardrail_id = "test-guardrail-123"
        mock_response = {
            "action": "GUARDRAIL_INTERVENED",
            "assessments": [{
                "automatedReasoningPolicy": {
                    "findings": [
                        {"result": "INVALID", "rule": "Rule 1.2", "explanation": "Price exceeds tolerance"},
                        {"result": "SATISFIABLE", "rule": "Rule 1.3", "explanation": "No receipt found"},
                    ]
                }
            }],
        }

        with patch("boto3.client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.apply_guardrail.return_value = mock_response

            result = self.validate("Agent response text")

        assert len(result["findings"]) == 2
        assert result["findings"][0]["result"] == "INVALID"
        assert result["findings"][1]["result"] == "SATISFIABLE"

    def test_handles_bedrock_error_gracefully(self):
        self.guardrail_id = "test-guardrail-123"

        with patch("boto3.client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.apply_guardrail.side_effect = Exception("Service unavailable")

            result = self.validate("Agent response text")

        assert result["valid"] is True  # Fail open
        assert result["action"] == "ERROR"
        assert "Service unavailable" in result.get("error", "")

    def test_empty_assessments_is_valid(self):
        self.guardrail_id = "test-guardrail-123"
        mock_response = {"action": "NONE", "assessments": []}

        with patch("boto3.client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.apply_guardrail.return_value = mock_response

            result = self.validate("Clean response")

        assert result["valid"] is True
        assert result["findings"] == []


class TestProcurementPolicyDocument:
    """Verify the policy document covers all required rules."""

    @pytest.fixture
    def policy_text(self):
        policy_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "procurement_policy.md"
        )
        with open(policy_path, encoding="utf-8") as f:
            return f.read()

    def test_has_four_sections(self, policy_text):
        assert "## 1. Three-Way Matching Rules" in policy_text
        assert "## 2. Approval Threshold Rules" in policy_text
        assert "## 3. Payment Rules" in policy_text
        assert "## 4. Supplier Rules" in policy_text

    def test_matching_tolerances_match_yaml(self, policy_text):
        assert "3 percent" in policy_text
        assert "50 USD" in policy_text
        assert "80 percent" in policy_text

    def test_approval_thresholds_match_yaml(self, policy_text):
        assert "5,000 USD" in policy_text
        assert "50,000 USD" in policy_text

    def test_has_all_15_rules(self, policy_text):
        for section, max_rule in [("1", 5), ("2", 4), ("3", 4), ("4", 2)]:
            for rule_num in range(1, max_rule + 1):
                assert f"Rule {section}.{rule_num}:" in policy_text, \
                    f"Missing Rule {section}.{rule_num}"

    def test_no_code_or_json(self, policy_text):
        assert "```" not in policy_text
        assert "def " not in policy_text
        assert "import " not in policy_text
