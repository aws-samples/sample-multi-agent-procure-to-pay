# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Invoice extraction service — extract structured data from PDF/image invoices.

Uses Amazon Bedrock with structured output (JSON schema) for reliable extraction.
Claude Sonnet 4.6 analyzes the document and returns a guaranteed JSON structure
via Bedrock's structured output feature (outputConfig.textFormat).

Fallback: Textract AnalyzeExpense for header fields if Bedrock fails.
"""

import base64
import json
import logging

import boto3

from config import settings

logger = logging.getLogger("p2p.extraction")

BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"

# JSON schema for structured output — Bedrock guarantees this format
INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_name": {
            "type": "string",
            "description": "Supplier/vendor company name exactly as printed on the invoice",
        },
        "invoice_number": {
            "type": "string",
            "description": "Invoice reference number / ID",
        },
        "invoice_date": {
            "type": "string",
            "description": "Invoice date in YYYY-MM-DD format",
        },
        "due_date": {
            "type": "string",
            "description": "Payment due date in YYYY-MM-DD format",
        },
        "po_number": {
            "type": "string",
            "description": "Purchase Order reference number (PO Ref field)",
        },
        "total_amount": {
            "type": "number",
            "description": "Total amount due on the invoice (numeric, no currency symbol)",
        },
        "subtotal": {
            "type": "number",
            "description": "Subtotal before tax (numeric)",
        },
        "tax_amount": {
            "type": "number",
            "description": "Tax amount (0 if no tax)",
        },
        "currency": {
            "type": "string",
            "description": "Currency code (e.g., USD, EUR)",
        },
        "payment_terms": {
            "type": "string",
            "description": "Payment terms (e.g., Net 30, 2/10 Net 30)",
        },
        "line_items": {
            "type": "array",
            "description": "All line items on the invoice",
            "items": {
                "type": "object",
                "properties": {
                    "item_code": {
                        "type": "string",
                        "description": "Item code / SKU / material number",
                    },
                    "description": {
                        "type": "string",
                        "description": "Item description / name",
                    },
                    "quantity": {
                        "type": "number",
                        "description": "Quantity invoiced",
                    },
                    "unit_of_measure": {
                        "type": "string",
                        "description": "Unit of measure (e.g., Nos, Kg, EA)",
                    },
                    "unit_price": {
                        "type": "number",
                        "description": "Price per unit (numeric)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Line total = quantity x unit_price",
                    },
                },
                "required": ["item_code", "description", "quantity", "unit_price", "amount"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "vendor_name", "invoice_number", "invoice_date", "due_date",
        "po_number", "total_amount", "line_items",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are an expert invoice data extraction system. Extract ALL fields from the invoice document with perfect accuracy.

Rules:
- Extract dates in YYYY-MM-DD format
- Extract amounts as plain numbers without currency symbols
- Extract EVERY line item from the invoice table — do not skip any rows
- Use the exact item codes, quantities, and prices shown on the document
- If a field is not present on the invoice, use an empty string for text or 0 for numbers"""


def extract_invoice_from_bytes(file_bytes: bytes) -> dict:
    """Extract structured invoice data from PDF/image bytes using Bedrock.

    Uses Claude Sonnet 4.6 with structured output (JSON schema) for guaranteed
    schema compliance. The PDF is sent as a base64-encoded document block.
    """
    try:
        result = _extract_with_bedrock(file_bytes)
        result["confidence"] = _assess_confidence(result)
        return result
    except Exception as e:
        logger.warning("Bedrock extraction failed, falling back to Textract: %s", e)
        return _extract_with_textract(file_bytes)


def extract_invoice_from_s3(bucket: str, key: str) -> dict:
    """Extract from an S3 object."""
    s3 = boto3.client("s3", region_name=settings.aws_region)
    obj = s3.get_object(Bucket=bucket, Key=key)
    file_bytes = obj["Body"].read()
    return extract_invoice_from_bytes(file_bytes)


def _extract_with_bedrock(file_bytes: bytes) -> dict:
    """Use Bedrock Converse API with structured output to extract invoice data."""
    bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_region)

    # Determine media type
    if file_bytes[:4] == b"%PDF":
        media_type = "application/pdf"
        doc_format = "pdf"
    elif file_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
        doc_format = "png"
    elif file_bytes[:2] == b"\xff\xd8":
        media_type = "image/jpeg"
        doc_format = "jpeg"
    else:
        media_type = "application/pdf"
        doc_format = "pdf"

    # Build the message with document block
    if media_type == "application/pdf":
        content_block = {
            "document": {
                "format": doc_format,
                "name": "vendor_invoice",
                "source": {"bytes": file_bytes},
            }
        }
    else:
        content_block = {
            "image": {
                "format": doc_format,
                "source": {"bytes": file_bytes},
            }
        }

    response = bedrock.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    content_block,
                    {"text": "Extract all invoice data from this document into the required JSON structure. Include every line item."},
                ],
            }
        ],
        inferenceConfig={"maxTokens": 4096, "temperature": 0},
        outputConfig={
            "textFormat": {
                "type": "json_schema",
                "structure": {
                    "jsonSchema": {
                        "schema": json.dumps(INVOICE_SCHEMA),
                        "name": "invoice_extraction",
                        "description": "Structured invoice data extracted from a vendor invoice document",
                    }
                },
            }
        },
    )

    # Parse the structured response
    output_text = ""
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            output_text += block["text"]

    result = json.loads(output_text)
    logger.info("Bedrock extraction: vendor=%s, invoice=%s, po=%s, total=%s, items=%d",
                result.get("vendor_name"), result.get("invoice_number"),
                result.get("po_number"), result.get("total_amount"),
                len(result.get("line_items", [])))

    return result


def _extract_with_textract(file_bytes: bytes) -> dict:
    """Fallback: Textract AnalyzeExpense for header fields."""
    textract = boto3.client("textract", region_name=settings.aws_region)
    response = textract.analyze_expense(Document={"Bytes": file_bytes})

    extracted = {
        "vendor_name": None,
        "invoice_number": None,
        "invoice_date": None,
        "due_date": None,
        "total_amount": None,
        "subtotal": None,
        "tax_amount": None,
        "po_number": None,
        "currency": None,
        "payment_terms": None,
        "line_items": [],
    }

    for doc in response.get("ExpenseDocuments", []):
        for field in doc.get("SummaryFields", []):
            field_type = field.get("Type", {}).get("Text", "")
            value = field.get("ValueDetection", {}).get("Text", "")

            if field_type == "VENDOR_NAME":
                extracted["vendor_name"] = value
            elif field_type == "INVOICE_RECEIPT_ID":
                extracted["invoice_number"] = value
            elif field_type == "INVOICE_RECEIPT_DATE":
                extracted["invoice_date"] = value
            elif field_type == "DUE_DATE":
                extracted["due_date"] = value
            elif field_type in ("TOTAL", "AMOUNT_DUE"):
                extracted["total_amount"] = _parse_amount(value)
            elif field_type == "SUBTOTAL":
                extracted["subtotal"] = _parse_amount(value)
            elif field_type == "TAX":
                extracted["tax_amount"] = _parse_amount(value)
            elif field_type == "PO_NUMBER":
                extracted["po_number"] = value
            elif field_type == "PAYMENT_TERMS":
                extracted["payment_terms"] = value

    extracted["confidence"] = _assess_confidence(extracted)
    return extracted


def _assess_confidence(extracted: dict) -> dict:
    """Assess extraction confidence based on field completeness."""
    required = ["vendor_name", "invoice_number", "total_amount", "po_number", "invoice_date"]
    present = sum(1 for f in required if extracted.get(f))
    has_line_items = len(extracted.get("line_items", [])) > 0

    if present == len(required) and has_line_items:
        tier = "AUTO_ACCEPT"
        overall = 98.0
    elif present >= 3 and has_line_items:
        tier = "REVIEW"
        overall = 85.0
    elif present >= 3:
        tier = "REVIEW"
        overall = 75.0
    else:
        tier = "MANUAL"
        overall = 50.0

    return {
        "overall": overall,
        "tier": tier,
        "fields_present": present,
        "fields_required": len(required),
        "has_line_items": has_line_items,
        "low_confidence_fields": [],
        "missing_fields": [f for f in required if not extracted.get(f)],
    }


def _parse_amount(text: str) -> float:
    """Parse a currency string like '$1,234.56' into a float."""
    if not text:
        return 0.0
    try:
        cleaned = text.replace("$", "").replace(",", "").replace(" ", "")
        for prefix in ("USD", "EUR", "GBP", "CAD", "AUD"):
            cleaned = cleaned.replace(prefix, "")
        return float(cleaned.strip())
    except (ValueError, TypeError):
        return 0.0
