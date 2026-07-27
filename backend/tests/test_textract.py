# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for Textract invoice extraction with confidence routing."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Prevent boto3 from trying to find AWS profiles at import time
os.environ.pop("AWS_PROFILE", None)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")


# --- Fixtures: realistic Textract AnalyzeExpense responses ---

def _make_field(field_type: str, value: str, confidence: float) -> dict:
    return {
        "Type": {"Text": field_type},
        "ValueDetection": {"Text": value, "Confidence": confidence},
    }


HIGH_CONFIDENCE_RESPONSE = {
    "ExpenseDocuments": [{
        "SummaryFields": [
            _make_field("VENDOR_NAME", "Acme Industrial Supply", 99.5),
            _make_field("INVOICE_RECEIPT_ID", "INV-2026-0042", 98.7),
            _make_field("INVOICE_RECEIPT_DATE", "2026-03-15", 97.2),
            _make_field("DUE_DATE", "2026-04-14", 96.1),
            _make_field("TOTAL", "$12,345.67", 99.1),
            _make_field("SUBTOTAL", "$11,223.34", 98.0),
            _make_field("TAX", "$1,122.33", 97.5),
            _make_field("PO_NUMBER", "PUR-ORD-2026-00015", 96.8),
            _make_field("CURRENCY", "USD", 99.9),
            _make_field("PAYMENT_TERMS", "Net 30", 95.5),
            _make_field("VENDOR_ADDRESS", "123 Industrial Blvd, Chicago IL 60601", 94.0),
            _make_field("RECEIVER_NAME", "P2P Agentic Corp", 98.0),
        ],
        "LineItemGroups": [{
            "LineItems": [
                {"LineItemExpenseFields": [
                    _make_field("ITEM", "Hex Bolt M10x50", 99.0),
                    _make_field("QUANTITY", "500", 99.0),
                    _make_field("UNIT_PRICE", "$0.55", 99.0),
                    _make_field("PRICE", "$275.00", 99.0),
                    _make_field("PRODUCT_CODE", "HEX-BOLT-M10", 99.0),
                ]},
                {"LineItemExpenseFields": [
                    _make_field("ITEM", "Hydraulic Cylinder 100mm", 99.0),
                    _make_field("QUANTITY", "10", 99.0),
                    _make_field("UNIT_PRICE", "$1,094.83", 99.0),
                    _make_field("PRICE", "$10,948.34", 99.0),
                    _make_field("PRODUCT_CODE", "HYD-CYL-100", 99.0),
                ]},
            ]
        }],
    }]
}

LOW_CONFIDENCE_RESPONSE = {
    "ExpenseDocuments": [{
        "SummaryFields": [
            _make_field("VENDOR_NAME", "Acm3 lndustr1al", 72.0),
            _make_field("INVOICE_RECEIPT_ID", "INV-2026-0042", 98.0),
            _make_field("TOTAL", "$12,345.67", 99.0),
            _make_field("PO_NUMBER", "PUR-ORD-???", 65.0),
        ],
        "LineItemGroups": [],
    }]
}

MEDIUM_CONFIDENCE_RESPONSE = {
    "ExpenseDocuments": [{
        "SummaryFields": [
            _make_field("VENDOR_NAME", "Acme Industrial", 88.0),
            _make_field("INVOICE_RECEIPT_ID", "INV-2026-0042", 98.0),
            _make_field("TOTAL", "$12,345.67", 99.0),
            _make_field("PO_NUMBER", "PUR-ORD-2026-00015", 91.0),
            _make_field("INVOICE_RECEIPT_DATE", "03/15/2026", 93.0),
        ],
        "LineItemGroups": [],
    }]
}


@pytest.fixture(autouse=True)
def mock_boto_and_settings():
    """Mock boto3 client and settings to prevent real AWS calls."""
    mock_client = MagicMock()
    with patch("services.textract.textract", mock_client), \
         patch("services.textract.settings") as mock_settings:
        mock_settings.aws_region = "us-east-1"
        mock_settings.bedrock_model_id = "us.anthropic.claude-sonnet-4-6-v1"
        yield mock_client, mock_settings


class TestParseExpenseResponse:
    def test_extracts_all_fields(self):
        from services.textract import _parse_expense_response

        result = _parse_expense_response(HIGH_CONFIDENCE_RESPONSE)

        assert result["vendor_name"] == "Acme Industrial Supply"
        assert result["invoice_number"] == "INV-2026-0042"
        assert result["invoice_date"] == "2026-03-15"
        assert result["due_date"] == "2026-04-14"
        assert result["total_amount"] == 12345.67
        assert result["subtotal"] == 11223.34
        assert result["tax_amount"] == 1122.33
        assert result["po_number"] == "PUR-ORD-2026-00015"
        assert result["currency"] == "USD"
        assert result["payment_terms"] == "Net 30"
        assert result["vendor_address"] == "123 Industrial Blvd, Chicago IL 60601"
        assert result["receiver_name"] == "P2P Agentic Corp"

    def test_extracts_line_items(self):
        from services.textract import _parse_expense_response

        result = _parse_expense_response(HIGH_CONFIDENCE_RESPONSE)

        assert len(result["line_items"]) == 2
        assert result["line_items"][0]["ITEM"] == "Hex Bolt M10x50"
        assert result["line_items"][0]["QUANTITY"] == "500"
        assert result["line_items"][0]["PRODUCT_CODE"] == "HEX-BOLT-M10"
        assert result["line_items"][1]["ITEM"] == "Hydraulic Cylinder 100mm"

    def test_stores_raw_fields_with_confidence(self):
        from services.textract import _parse_expense_response

        result = _parse_expense_response(HIGH_CONFIDENCE_RESPONSE)

        assert "VENDOR_NAME" in result["raw_fields"]
        assert result["raw_fields"]["VENDOR_NAME"]["confidence"] == 99.5
        assert result["raw_fields"]["TOTAL"]["value"] == "$12,345.67"

    def test_handles_empty_response(self):
        from services.textract import _parse_expense_response

        result = _parse_expense_response({"ExpenseDocuments": []})

        assert result["vendor_name"] is None
        assert result["total_amount"] is None
        assert result["line_items"] == []


class TestAssessConfidence:
    def test_high_confidence_auto_accept(self):
        from services.textract import _parse_expense_response, _assess_confidence

        extracted = _parse_expense_response(HIGH_CONFIDENCE_RESPONSE)
        confidence = _assess_confidence(extracted)

        assert confidence["tier"] == "AUTO_ACCEPT"
        assert confidence["overall"] > 95
        assert confidence["low_confidence_fields"] == []
        assert confidence["missing_fields"] == []

    def test_low_confidence_manual(self):
        from services.textract import _parse_expense_response, _assess_confidence

        extracted = _parse_expense_response(LOW_CONFIDENCE_RESPONSE)
        confidence = _assess_confidence(extracted)

        assert confidence["tier"] == "MANUAL"
        low_fields = [f["field"] for f in confidence["low_confidence_fields"]]
        assert "VENDOR_NAME" in low_fields
        assert "PO_NUMBER" in low_fields

    def test_medium_confidence_review(self):
        from services.textract import _parse_expense_response, _assess_confidence

        extracted = _parse_expense_response(MEDIUM_CONFIDENCE_RESPONSE)
        confidence = _assess_confidence(extracted)

        assert confidence["tier"] == "REVIEW"
        low_fields = [f["field"] for f in confidence["low_confidence_fields"]]
        assert "VENDOR_NAME" in low_fields

    def test_missing_critical_field_is_manual(self):
        from services.textract import _parse_expense_response, _assess_confidence

        response = {"ExpenseDocuments": [{"SummaryFields": [
            _make_field("INVOICE_RECEIPT_ID", "INV-001", 99.0),
        ], "LineItemGroups": []}]}
        extracted = _parse_expense_response(response)
        confidence = _assess_confidence(extracted)

        assert confidence["tier"] == "MANUAL"
        assert "VENDOR_NAME" in confidence["missing_fields"]
        assert "TOTAL" in confidence["missing_fields"]


class TestParseAmount:
    def test_standard_amount(self):
        from services.textract import _parse_amount
        assert _parse_amount("$1,234.56") == 1234.56

    def test_no_currency_symbol(self):
        from services.textract import _parse_amount
        assert _parse_amount("1234.56") == 1234.56

    def test_with_currency_prefix(self):
        from services.textract import _parse_amount
        assert _parse_amount("USD 1234.56") == 1234.56

    def test_empty_string(self):
        from services.textract import _parse_amount
        assert _parse_amount("") == 0.0

    def test_invalid_string(self):
        from services.textract import _parse_amount
        assert _parse_amount("N/A") == 0.0


class TestValidateWithBedrock:
    def test_skips_when_no_low_confidence_fields(self):
        from services.textract import _validate_with_bedrock

        extracted = {
            "vendor_name": "Acme",
            "confidence": {"low_confidence_fields": []},
        }
        result = _validate_with_bedrock(extracted)
        assert result == {}

    def test_calls_bedrock_and_returns_corrections(self):
        with patch("services.textract.boto3") as mock_boto3:
            mock_bedrock = MagicMock()
            mock_boto3.client.return_value = mock_bedrock

            body_content = json.dumps({
                "content": [{"text": '{"vendor_name": "Acme Industrial Supply"}'}]
            }).encode()
            mock_response_body = MagicMock()
            mock_response_body.read.return_value = body_content
            mock_bedrock.invoke_model.return_value = {"body": mock_response_body}

            from services.textract import _validate_with_bedrock

            extracted = {
                "vendor_name": "Acm3 lndustr1al",
                "invoice_number": "INV-001",
                "confidence": {
                    "low_confidence_fields": [
                        {"field": "VENDOR_NAME", "value": "Acm3 lndustr1al",
                         "confidence": 72.0, "threshold": 90}
                    ]
                },
                "line_items": [],
            }
            result = _validate_with_bedrock(extracted)
            assert result == {"vendor_name": "Acme Industrial Supply"}


class TestApplyCorrections:
    def test_applies_corrections_in_place(self):
        from services.textract import _apply_corrections

        extracted = {"vendor_name": "Acm3", "invoice_number": "INV-001"}
        _apply_corrections(extracted, {"vendor_name": "Acme Industrial"})
        assert extracted["vendor_name"] == "Acme Industrial"
        assert extracted["invoice_number"] == "INV-001"

    def test_ignores_unknown_fields(self):
        from services.textract import _apply_corrections

        extracted = {"vendor_name": "Acme"}
        _apply_corrections(extracted, {"nonexistent_field": "value"})
        assert "nonexistent_field" not in extracted
