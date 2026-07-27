# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
LLM-powered document generator using Bedrock Converse API with structured outputs.

Uses toolConfig to enforce JSON schema compliance, producing realistic P2P
documents that vary naturally (different quantities, prices, urgency, etc.)
instead of purely random generation.

Reference: https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html
"""

import json
import logging
from typing import Optional

import boto3

from .config import AWS_REGION

logger = logging.getLogger(__name__)

_bedrock = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    return _bedrock


# ---------------------------------------------------------------------------
# JSON Schemas for structured output (match canonical models)
# ---------------------------------------------------------------------------

REQUISITION_SCHEMA = {
    "type": "object",
    "properties": {
        "required_date": {
            "type": "string",
            "description": "ISO date when materials are needed (YYYY-MM-DD), 7-30 days from now",
        },
        "purpose": {
            "type": "string",
            "description": "Business reason for the purchase, 1-2 sentences. Be specific about which production line, maintenance job, or project needs these materials.",
        },
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_number": {"type": "integer"},
                    "item_id": {"type": "string", "description": "Item code from the catalog"},
                    "quantity": {"type": "integer", "description": "Reasonable quantity for a manufacturing plant (5-500)"},
                    "unit_of_measure": {"type": "string"},
                    "unit_price": {"type": "number", "description": "Price near the catalog standard rate (+/- 10%)"},
                    "delivery_date": {"type": "string"},
                },
                "required": ["line_number", "item_id", "quantity", "unit_of_measure", "unit_price"],
            },
            "minItems": 1,
            "maxItems": 6,
        },
    },
    "required": ["required_date", "purpose", "line_items"],
}

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_id": {"type": "string"},
        "vendor_invoice_number": {
            "type": "string",
            "description": "Realistic supplier invoice number (e.g., ACME-INV-2025-XXXX)",
        },
        "invoice_date": {"type": "string"},
        "due_date": {"type": "string"},
        "order_id": {"type": "string", "description": "The PO number this invoice references"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_number": {"type": "integer"},
                    "item_id": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "line_amount": {"type": "number"},
                    "order_id": {"type": "string"},
                },
                "required": ["line_number", "item_id", "quantity", "unit_price", "line_amount"],
            },
        },
    },
    "required": ["supplier_id", "vendor_invoice_number", "invoice_date", "due_date", "line_items"],
}


def generate_requisition(
    scenario_description: str,
    available_items: list[dict],
    model_id: str = "us.anthropic.claude-sonnet-4-6",
) -> dict:
    """Use Bedrock to generate a realistic requisition.

    Args:
        scenario_description: What kind of requisition to generate (e.g.,
            "happy_path", "high value escalation", "urgent safety restock")
        available_items: List of item catalog entries the LLM can choose from.
        model_id: Bedrock model to use.

    Returns:
        Dict matching RequisitionCreate schema, ready for the canonical API.
    """
    items_context = json.dumps(
        [{"item_code": i["item_code"], "item_name": i["item_name"],
          "item_group": i.get("item_group", ""), "uom": i.get("uom", "Nos"),
          "catalog_price": i.get("unit_price", i.get("standard_rate", 10))}
         for i in available_items],
        indent=2,
    )

    tool_def = {
        "toolSpec": {
            "name": "create_requisition",
            "description": "Create a purchase requisition for a manufacturing plant.",
            "inputSchema": {"json": REQUISITION_SCHEMA},
        }
    }

    messages = [
        {
            "role": "user",
            "content": [{"text": (
                f"Generate a realistic purchase requisition for a manufacturing company called P2P Agentic Corp.\n\n"
                f"Scenario: {scenario_description}\n\n"
                f"Available items in catalog:\n{items_context}\n\n"
                f"Rules:\n"
                f"- Pick 1-4 items that make sense together for the scenario\n"
                f"- Quantities should be realistic for a mid-size factory (not 1, not 10000)\n"
                f"- Prices should be close to catalog price (+/- 10%)\n"
                f"- Purpose should be specific and believable\n"
                f"- required_date should be 7-30 days from today (use 2025-04-XX format)\n"
                f"\nUse the create_requisition tool to output the requisition."
            )}],
        }
    ]

    return _call_with_tool(messages, tool_def, model_id)


def generate_invoice_data(
    purchase_order: dict,
    scenario_type: str = "clean",
    model_id: str = "us.anthropic.claude-sonnet-4-6",
) -> dict:
    """Use Bedrock to generate a realistic invoice based on a PO.

    Args:
        purchase_order: The PO dict from the canonical API.
        scenario_type: "clean" (matches PO), "price_variance" (5-15% over),
            "quantity_mismatch" (different qty), "partial" (subset of lines).
        model_id: Bedrock model to use.

    Returns:
        Dict matching InvoiceCreate schema, ready for the canonical API.
    """
    po_context = json.dumps({
        "order_id": purchase_order.get("order_id", ""),
        "supplier_id": purchase_order.get("supplier_id", ""),
        "supplier_name": purchase_order.get("supplier_name", ""),
        "total_amount": purchase_order.get("total_amount", 0),
        "line_items": purchase_order.get("line_items", []),
    }, indent=2)

    tool_def = {
        "toolSpec": {
            "name": "create_invoice",
            "description": "Create a purchase invoice from a supplier.",
            "inputSchema": {"json": INVOICE_SCHEMA},
        }
    }

    variance_instructions = {
        "clean": "Invoice should exactly match PO quantities and prices.",
        "price_variance": "Invoice should have 5-15% HIGHER prices on 1-2 line items compared to PO. This simulates a supplier price increase.",
        "quantity_mismatch": "Invoice should claim 5-20% MORE quantity on one line item than the PO. This simulates an invoicing error.",
        "partial": "Invoice should only include 2 of the PO's line items. This simulates progress billing.",
    }

    messages = [
        {
            "role": "user",
            "content": [{"text": (
                f"Generate a realistic supplier invoice for this purchase order:\n\n"
                f"PO Data:\n{po_context}\n\n"
                f"Scenario: {variance_instructions.get(scenario_type, variance_instructions['clean'])}\n\n"
                f"Rules:\n"
                f"- vendor_invoice_number should look realistic (e.g., ACME-INV-2025-0XXX)\n"
                f"- invoice_date should be today or recent (2025-04-XX)\n"
                f"- due_date should be 30 days after invoice_date\n"
                f"- line_amount = quantity * unit_price for each line\n"
                f"- Include the order_id reference\n"
                f"\nUse the create_invoice tool to output the invoice."
            )}],
        }
    ]

    return _call_with_tool(messages, tool_def, model_id)


def _call_with_tool(messages: list, tool_def: dict, model_id: str) -> dict:
    """Call Bedrock Converse API with a tool definition for structured output."""
    bedrock = _get_bedrock()

    try:
        response = bedrock.converse(
            modelId=model_id,
            messages=messages,
            toolConfig={
                "tools": [tool_def],
                "toolChoice": {"tool": {"name": tool_def["toolSpec"]["name"]}},
            },
            inferenceConfig={
                "maxTokens": 2048,
                "temperature": 0.7,  # Some creativity for variety
            },
        )

        # Extract tool use from response
        output = response.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])

        for block in content:
            if "toolUse" in block:
                return block["toolUse"]["input"]

        logger.warning("No tool use found in Bedrock response, falling back to text parse")
        # Try to extract JSON from text blocks
        for block in content:
            if "text" in block:
                text = block["text"]
                if "{" in text:
                    import re
                    match = re.search(r"\{.*\}", text, re.DOTALL)
                    if match:
                        return json.loads(match.group())

        raise ValueError("Could not extract structured output from Bedrock response")

    except Exception as e:
        # nosemgrep -- logging-error-without-handling: best-effort demo path; failure is non-fatal and logged
        logger.error("Bedrock structured output generation failed: %s", e)
        raise
