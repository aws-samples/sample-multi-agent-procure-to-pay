# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Per-tool-call progress events via Strands hooks.

Hooks into BeforeToolCallEvent to push real-time progress messages
onto an asyncio.Queue, bridging synchronous agent execution to the
async SSE generator in agentcore_app.py.
"""

import asyncio
import json
import logging
from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import BeforeToolCallEvent

logger = logging.getLogger("p2p.progress_hooks")

# Map tool names to business-language descriptions (for UI progress display)
TOOL_DESCRIPTIONS = {
    # MCP tools (via Gateway — canonical names)
    "erp___list_suppliers": "Checking suppliers in the ERP system",
    "erp___get_supplier": "Looking up supplier details",
    "erp___list_items": "Checking item catalog",
    "erp___get_item": "Looking up item details",
    "erp___list_requisitions": "Scanning recent requisitions",
    "erp___get_requisition": "Pulling the requisition for review",
    "erp___create_requisition": "Creating a new requisition",
    "erp___list_purchase_orders": "Reviewing purchase order history",
    "erp___get_purchase_order": "Pulling the purchase order for comparison",
    "erp___create_purchase_order": "Generating a new purchase order",
    "erp___list_receipts": "Checking goods receipt records",
    "erp___get_receipt": "Pulling receipt details",
    "erp___list_invoices": "Checking invoice records",
    "erp___get_invoice": "Retrieving the invoice details",
    "erp___create_invoice": "Creating a new invoice",
    "erp___list_payments": "Reviewing payment history",
    "erp___create_payment": "Scheduling a payment",
    "erp___get_spend_summary": "Pulling spend analytics",
    "erp___get_supplier_performance": "Evaluating supplier performance metrics",
    "erp___get_budget_status": "Checking cost center budget vs actual spend",
    "erp___extract_invoice_document": "Extracting invoice data from uploaded document",
    "erp___list_payment_terms": "Checking available payment terms",
    # Local computation tools
    "check_budget": "Checking cost center budget",
    "get_framework_agreements": "Checking framework agreements",
    "get_blanket_pos": "Checking blanket purchase orders",
    # Code Interpreter
    "code_interpreter": "Running computational analysis in secure sandbox",
}


class _ToolProgressHook(HookProvider):
    """Pushes tool-call progress events onto an asyncio.Queue."""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop, agent_name: str):
        self._queue = queue
        self._loop = loop
        self._agent_name = agent_name

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._on_before_tool)

    def _on_before_tool(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use.get("name", "unknown")
        description = TOOL_DESCRIPTIONS.get(tool_name, f"Using {tool_name}")
        msg = {
            "type": "progress",
            "step": description,
            "agent": self._agent_name,
            "tool": tool_name,
        }
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, msg)
        except Exception:
            logger.debug("Failed to enqueue progress for %s", tool_name)


_SENTINEL = object()


class ProgressBridge:
    """Bridge between synchronous Strands agent execution and async SSE streaming.

    Creates a hook provider + asyncio.Queue. The agent runs in a thread via
    asyncio.to_thread(); tool-call progress events are yielded in real-time.

    Usage:
        bridge = ProgressBridge("requisition")
        agent = Agent(model=model, tools=tools, hooks=[bridge.hook_provider])
        async for event_line in bridge.run(agent, prompt):
            yield event_line  # send to SSE client
        result = bridge.result  # the Strands AgentResult
    """

    def __init__(self, agent_name: str):
        self._agent_name = agent_name
        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop = asyncio.get_event_loop()
        self._hook = _ToolProgressHook(self._queue, self._loop, agent_name)
        self.result = None

    @property
    def hook_provider(self) -> _ToolProgressHook:
        return self._hook

    async def run(self, agent_obj, prompt: str):
        """Async generator: yields JSON progress lines, stores result in self.result."""
        async def _execute():
            r = await asyncio.to_thread(agent_obj, prompt)
            self._queue.put_nowait(_SENTINEL)
            return r

        task = asyncio.create_task(_execute())

        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                break
            yield json.dumps(item) + "\n"

        self.result = await task
