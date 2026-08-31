# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Chat Agent — general-purpose P2P assistant.

Unlike the specialized agents (which run on AgentCore Runtime with MCP Gateway),
the chat agent runs on Lambda and uses REST adapter tools with per-user ERPNext
credentials. This is because the MCP Gateway doesn't propagate user identity —
it uses the Lambda's IAM role, losing per-user ERP attribution.

The REST wrappers reach the adapter through services/erp_client.py, passing the
email from the request's verified JWT claims, so requisitions created via chat
are attributed to the logged-in user.
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("p2p.agents.chat")

SYSTEM_PROMPT = """You are ARIA — an AI procurement assistant for the P2P (Procure-to-Pay) pipeline.
You help users across all roles: requesters, approvers, AP clerks, executives, and procurement officers.

RESPONSE RULES:
- ALWAYS call a tool FIRST before answering any data question. NEVER guess or fabricate data.
- Use bullet points, keep answers under 15 lines.
- Format currency as $X,XXX.XX. Never use markdown tables.
- If a tool returns an empty list, say "No results found" — don't invent data.
- NEVER invent numbers, prices, quantities, or vendor names. Every data point must come from a tool call.

AVAILABLE ERP TOOLS (18 tools):
- erp__list_items / erp__get_item — catalog lookup
- erp__list_requisitions / erp__get_requisition / erp__create_requisition — requisition management
- erp__update_requisition_status — approve or reject a requisition (approvers only)
- erp__list_purchase_orders / erp__get_purchase_order — PO queries
- erp__list_invoices / erp__get_invoice — invoice queries
- erp__list_suppliers / erp__get_supplier — supplier directory and details
- erp__list_receipts / erp__get_receipt — goods receipt tracking
- erp__list_payments — payment history
- erp__get_spend_summary — aggregate spend metrics
- erp__get_supplier_performance — per-supplier delivery metrics
- erp__get_budget_status — budget vs actual by cost center
"""

REQUESTER_PROMPT = """

## REQUESTER-SPECIFIC INSTRUCTIONS

You are helping a REQUESTER create purchase requisitions. Follow this flow:

1. When the user asks to order something, call erp__list_items with their keywords as the search parameter.

2. **One match found**: Show the item details (name, price, item_id) and ask the user to confirm quantity. Then ask: "Would you like to add anything else to this requisition, or shall I create it?"

3. **Multiple matches found**: List the options (item_id, name, price) and ask the user to pick one.

4. **No match found**: Tell the user "That item is not in our catalog. Please check the item name or contact procurement."

5. **Before creating**: Always confirm the full order summary with the user:
   "Here's your requisition summary:
   - {quantity}× {item_name} @ ${price} = ${line_total}
   Total: **${total}**
   Would you like to add more items, or shall I submit this?"

6. **After confirmation**: Call erp__create_requisition with all items and catalog pricing.

7. Report back: "Created PR **{requisition_id}** for {quantity}× {item_name} — total **${amount}**. You can run the approval workflow from the Requisitions page."

CRITICAL REQUESTER RULES:
- NEVER ask the user for a price — use the catalog standard_rate automatically
- NEVER ask the user for a supplier — the Sourcing Agent handles that later
- Always confirm the order summary before creating the requisition
- Cost center is automatically assigned from your department — do NOT ask the user for it
- If the user says "cancel" or "no", do NOT create a PR
"""


DEPT_COST_CENTER = {
    "Manufacturing": "Manufacturing - AMG",
    "Maintenance": "Maintenance - AMG",
    "Lab": "Engineering - AMG",
    "Quality": "Engineering - AMG",
    "Engineering": "Engineering - AMG",
    "Warehouse": "Operations - AMG",
    "Facilities": "Safety - AMG",
    "Operations": "Operations - AMG",
}


def _build_erp_tools_rest(user_email: str = "", role: str = "admin",
                          user_department: str = ""):
    """Build ERP tools via the canonical adapter with per-user identity.

    `user_email` comes from the verified JWT claims of the chat request, so
    write operations (create_requisition) are attributed to the logged-in user.
    """
    from strands import tool
    from services import erp_client

    if not erp_client.is_configured():
        logger.warning("ERP adapter transport not configured — ERP tools unavailable for chat agent")
        return []

    def _get(path: str, params: dict = None) -> str:
        try:
            resp = erp_client.request(
                "GET", path, params=params, user_email=user_email or None, timeout=15,
            )
            resp.raise_for_status()
            return json.dumps(resp.json())
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _post(path: str, data: dict) -> str:
        try:
            resp = erp_client.request(
                "POST", path, json_body=data, user_email=user_email or None, timeout=15,
            )
            resp.raise_for_status()
            return json.dumps(resp.json())
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def erp__list_items(group: str = "", search: str = "") -> str:
        """List items from the ERP catalog. Filter by item group or search by name."""
        p = {}
        if group: p["group"] = group
        if search: p["search"] = search
        return _get("/items", params=p or None)

    @tool
    def erp__get_item(item_id: str) -> str:
        """Get details of a specific item by its item code (e.g., MAT-FS-001)."""
        return _get(f"/items/{item_id}")

    @tool
    def erp__list_requisitions(status: str = "", requester: str = "") -> str:
        """List purchase requisitions. Filter by status or requester."""
        p = {}
        if status: p["status"] = status
        req = requester or (user_email if role == "requester" else "")
        if req: p["requester"] = req
        return _get("/requisitions", params=p)

    @tool
    def erp__get_requisition(requisition_id: str) -> str:
        """Get details of a specific requisition including line items."""
        return _get(f"/requisitions/{requisition_id}")

    @tool
    def erp__create_requisition(items: list, schedule_date: str = "", cost_center: str = "") -> str:
        """Create a new purchase requisition. Each item must be {"item_id": "<code>", "quantity": <num>, "unit_price": <catalog_rate>}. Always include the standard_rate from the catalog as unit_price. Cost center is auto-assigned from user department if not specified."""
        data = {"line_items": items}
        if schedule_date:
            data["required_date"] = schedule_date
        resolved_cc = cost_center or DEPT_COST_CENTER.get(user_department, "")
        if resolved_cc:
            data["cost_center"] = resolved_cc
        if user_department:
            data["department"] = f"{user_department} - AMG"
        return _post("/requisitions", data)

    @tool
    def erp__list_purchase_orders(supplier_id: str = "", status: str = "") -> str:
        """List purchase orders. Filter by supplier or status."""
        p = {}
        if supplier_id: p["supplier_id"] = supplier_id
        if status: p["status"] = status
        return _get("/purchase-orders", params=p or None)

    @tool
    def erp__get_purchase_order(order_id: str) -> str:
        """Get details of a specific purchase order with line items."""
        return _get(f"/purchase-orders/{order_id}")

    @tool
    def erp__list_invoices(supplier_id: str = "", status: str = "") -> str:
        """List invoices. Filter by supplier or status."""
        p = {}
        if supplier_id: p["supplier_id"] = supplier_id
        if status: p["status"] = status
        return _get("/invoices", params=p or None)

    @tool
    def erp__get_invoice(invoice_id: str) -> str:
        """Get details of a specific invoice with line items."""
        return _get(f"/invoices/{invoice_id}")

    @tool
    def erp__list_suppliers(status: str = "", group: str = "") -> str:
        """List suppliers. Filter by status or supplier group."""
        p = {}
        if status: p["status"] = status
        if group: p["group"] = group
        return _get("/suppliers", params=p or None)

    @tool
    def erp__list_receipts(order_id: str = "") -> str:
        """List goods receipts. Filter by purchase order."""
        p = {"order_id": order_id} if order_id else None
        return _get("/receipts", params=p)

    @tool
    def erp__get_receipt(receipt_id: str) -> str:
        """Get details of a specific goods receipt with line items."""
        return _get(f"/receipts/{receipt_id}")

    @tool
    def erp__get_supplier(supplier_id: str) -> str:
        """Get detailed information for a specific supplier including contact info and performance."""
        return _get(f"/suppliers/{supplier_id}")

    @tool
    def erp__list_payments() -> str:
        """List all payment entries with status, amounts, and dates."""
        return _get("/payments")

    @tool
    def erp__update_requisition_status(requisition_id: str, status: str) -> str:
        """Update the status of a requisition. Used by approvers to approve or reject.

        Args:
            requisition_id: The requisition ID to update.
            status: New status — "approved" or "rejected".
        """
        return _post(f"/requisitions/{requisition_id}/status", {"status": status})

    @tool
    def erp__get_spend_summary() -> str:
        """Get aggregated spend metrics: total spend, order counts, invoice stats."""
        return _get("/analytics/spend-summary")

    @tool
    def erp__get_supplier_performance() -> str:
        """Get per-supplier delivery and quality performance metrics."""
        return _get("/analytics/supplier-performance")

    @tool
    def erp__get_budget_status(cost_center: str = "") -> str:
        """Get budget vs actual spend for cost centers."""
        p = {"cost_center": cost_center} if cost_center else None
        return _get("/analytics/budget-status", params=p)

    @tool
    def erp__list_cost_centers() -> str:
        """List available cost centers for budget allocation."""
        return _get("/cost-centers")

    tools = [
        erp__list_items, erp__get_item,
        erp__list_requisitions, erp__get_requisition, erp__create_requisition,
        erp__update_requisition_status,
        erp__list_purchase_orders, erp__get_purchase_order,
        erp__list_invoices, erp__get_invoice,
        erp__list_suppliers, erp__get_supplier,
        erp__list_receipts, erp__get_receipt,
        erp__list_payments,
        erp__get_spend_summary, erp__get_supplier_performance, erp__get_budget_status,
        erp__list_cost_centers,
    ]
    logger.info("Built %d ERP tools via REST adapter", len(tools))
    return tools


def invoke(message: str, role: str = "admin", role_context: str = "",
           conversation_history: list[dict] = None, bedrock_model_id: str = None,
           user_email: str = "", user_department: str = "") -> dict:
    """Invoke the Chat Agent with a user message.

    Uses REST adapter tools with per-user ERPNext credentials for user attribution.
    """
    from config import settings

    model_id = bedrock_model_id or settings.bedrock_model_id

    try:
        from strands import Agent
        from strands.models import BedrockModel

        model = BedrockModel(model_id=model_id, streaming=False)
        tools = _build_erp_tools_rest(user_email=user_email, role=role,
                                       user_department=user_department)

        # Build system prompt with role context + user identity
        system = SYSTEM_PROMPT
        if role_context:
            system = f"{role_context}\n\n{SYSTEM_PROMPT}"
        if user_email:
            system += f'\n\nThe current logged-in user is {user_email}. When they say "my" requisitions/orders/invoices, filter by requester="{user_email}".'
        if role == "requester":
            system += REQUESTER_PROMPT

        # Build Strands messages for multi-turn (no text injection)
        messages = []
        if conversation_history:
            for m in conversation_history[-6:]:
                r = m.get("role", "user")
                c = m.get("content", "")
                if r == "user":
                    messages.append({"role": "user", "content": [{"text": c}]})
                elif r == "assistant":
                    messages.append({"role": "assistant", "content": [{"text": c}]})

        agent = Agent(model=model, tools=tools, system_prompt=system, messages=messages)
        result = agent(message)

        response_text = ""
        if hasattr(result, "message") and result.message:
            content = result.message.get("content", [])
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    response_text += block["text"]
                elif isinstance(block, str):
                    response_text += block
        if not response_text:
            response_text = str(result)

        logger.info(f"Chat agent [{role}] responded: {response_text[:100]}...")

        return {
            "response": response_text,
            "timestamp": datetime.utcnow().isoformat(),
            "role": role,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Chat agent [{role}] failed: {e}\n{tb}")
        err_msg = str(e) or repr(e) or "Unknown error"
        return {
            "response": f"I encountered an error processing your request: {err_msg}",
            "error": err_msg,
            "timestamp": datetime.utcnow().isoformat(),
        }
