# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Local stand-in for the AgentCore Gateway (MCP tools over the canonical API).

In the cloud, the AgentCore Gateway fronts the canonical P2P REST API
(backend/adapters/canonical_api.py) and auto-generates MCP tools from its OpenAPI
spec, exposing them over streamable-HTTP with names prefixed by the target name:
``erp___<operation_id>`` (three underscores). Agents connect via
backend/utils/mcp_client.py (GATEWAY_ENDPOINT) and call those prefixed tools;
backend/utils/progress_hooks.py also keys progress messages on the ``erp___``
names.

This shim reproduces that locally with FastMCP: it imports the canonical API's
FastAPI ``app`` object directly, turns every operation into an MCP tool, renames
each to ``erp___<operation_id>`` to match the Gateway's target prefix, and serves
it over streamable-HTTP at ``/mcp``. Because GATEWAY_ENDPOINT points here, the
unmodified agent code reaches these tools exactly as it reaches the real Gateway.

The canonical API runs in-process here (its own SigV4/Gateway auth is bypassed —
the agent→gateway hop is local and unauthenticated), and its ERP calls hit the
local ERPNext via ERPNEXT_URL. No application code changes.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s mcp-gateway-shim %(message)s"
)
logger = logging.getLogger("mcp_gateway_shim")

# The Gateway target name; tools are exposed as "<TARGET>___<operation_id>".
_TARGET_PREFIX = os.environ.get("ARIA_MCP_TARGET_PREFIX", "erp")


def _build() -> "object":
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    sys.path.insert(0, str(backend_dir))

    from fastmcp import FastMCP
    # Importing the module runs _bootstrap_from_secret() and builds the FastAPI
    # app; endpoint env vars (Secrets Manager -> moto) are already set by the
    # supervisor, so the bootstrap reads the local secret.
    from adapters import canonical_api

    fastapi_app = canonical_api.app

    # Map each route's operation_id -> the Gateway-style prefixed tool name so
    # agents' erp___* tool calls (and progress_hooks) resolve unchanged.
    mcp_names: dict[str, str] = {}
    for route in fastapi_app.routes:
        op_id = getattr(route, "operation_id", None) or getattr(route, "name", None)
        if op_id and re.fullmatch(r"[a-z_]+", op_id):
            mcp_names[op_id] = f"{_TARGET_PREFIX}___{op_id}"

    mcp = FastMCP.from_fastapi(app=fastapi_app, name="p2p-erp-gateway", mcp_names=mcp_names)

    # FastMCP sanitizes tool names by collapsing runs of underscores
    # (``__+`` -> ``_``), which turns our intended ``erp___op`` into ``erp_op``.
    # The Gateway advertises the triple-underscore form and agents' progress
    # display (backend/utils/progress_hooks.py) keys on it, so restore the exact
    # ``erp___<operation_id>`` names by re-keying the tool manager post-build.
    tm = mcp._tool_manager
    for key in list(tm._tools.keys()):
        tool = tm._tools[key]
        # collapsed "erp_<op>" -> canonical "erp___<op>"
        if key.startswith(f"{_TARGET_PREFIX}_") and not key.startswith(f"{_TARGET_PREFIX}___"):
            op = key[len(_TARGET_PREFIX) + 1:]
            canonical = f"{_TARGET_PREFIX}___{op}"
            tool.name = canonical
            del tm._tools[key]
            tm._tools[canonical] = tool

    logger.info("built MCP gateway with %d tools (prefix %s___)", len(tm._tools), _TARGET_PREFIX)
    return mcp


def main() -> None:
    port = int(os.environ.get("ARIA_MCP_GATEWAY_PORT", "8002"))
    mcp = _build()
    logger.info("MCP gateway shim serving streamable-http on http://127.0.0.1:%d/mcp", port)
    # streamable-http transport, path /mcp — matches GATEWAY_ENDPOINT.
    mcp.run(transport="http", host="127.0.0.1", port=port, path="/mcp")


if __name__ == "__main__":
    main()
