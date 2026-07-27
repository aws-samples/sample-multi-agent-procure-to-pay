# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Single source of truth for the local harness wiring.

Everything "local" lives here and in the shims — never in ``backend/``. The
harness works on Lumina's principle: local-ness is entirely configuration.
botocore natively honors ``AWS_ENDPOINT_URL_<SERVICE>`` env vars, so pointing
those at emulators/shims reroutes the unmodified application code. Bedrock's
endpoint var is deliberately left unset so agent model calls hit real AWS.

This module is imported by the supervisor and the shims to build a consistent
process environment; it reads overridable values from the OS environment
(populated from ``local/.env``) and falls back to sensible local defaults.
"""

from __future__ import annotations

import os

# --- Ports (override via local/.env if they collide with something local) ---
# The SPA is served by Vite on :5173 (its default); ERPNext's local-test compose
# publishes :8080. The backend + shims take the 8000s/9000s below.
BACKEND_PORT = int(os.environ.get("ARIA_BACKEND_PORT", "8000"))         # uvicorn main:app
CANONICAL_API_PORT = int(os.environ.get("ARIA_CANONICAL_API_PORT", "8001"))  # ERP canonical FastAPI
MCP_GATEWAY_PORT = int(os.environ.get("ARIA_MCP_GATEWAY_PORT", "8002"))  # fastmcp over canonical API
AGENT_PROXY_PORT = int(os.environ.get("ARIA_AGENT_PROXY_PORT", "8003"))  # browser-facing agent proxy
AGENTCORE_SHIM_PORT = int(os.environ.get("ARIA_AGENTCORE_SHIM_PORT", "9000"))  # runtime+memory shim
# moto server mode emulates DynamoDB, S3, and Secrets Manager on ONE port — no
# separate DynamoDB Local / Java process needed.
MOTO_PORT = int(os.environ.get("ARIA_MOTO_PORT", "5100"))

# One local port per specialized agent (all run backend/agentcore_app.py with a
# different AGENT_NAME). The runtime shim maps an ARN's kind token to these.
AGENT_PORTS = {
    "requisition": int(os.environ.get("ARIA_AGENT_REQUISITION_PORT", "8081")),
    "sourcing": int(os.environ.get("ARIA_AGENT_SOURCING_PORT", "8082")),
    "po_management": int(os.environ.get("ARIA_AGENT_PO_MANAGEMENT_PORT", "8083")),
    "receiving": int(os.environ.get("ARIA_AGENT_RECEIVING_PORT", "8084")),
    "invoice_matching": int(os.environ.get("ARIA_AGENT_INVOICE_MATCHING_PORT", "8085")),
    "payment": int(os.environ.get("ARIA_AGENT_PAYMENT_PORT", "8086")),
    "workflow": int(os.environ.get("ARIA_AGENT_WORKFLOW_PORT", "8087")),
}

REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_PREFIX = os.environ.get("ARIA_TABLE_PREFIX", "p2p-dev")
S3_BUCKET = os.environ.get("ARIA_S3_BUCKET", "p2p-dev-documents")
ERPNEXT_SECRET_NAME = os.environ.get("ARIA_ERPNEXT_SECRET_NAME", "p2p-dev-erpnext")

# Local ERPNext (infra/docker/docker-compose.local-test.yaml publishes :8080).
ERPNEXT_URL = os.environ.get("ERPNEXT_URL", "http://localhost:8080")

# Placeholder runtime ARNs. The kind token (trailing segment) is what the
# runtime shim routes on; account id is a dummy since nothing hits real AgentCore.
_ARN_TMPL = "arn:aws:bedrock-agentcore:{region}:000000000000:runtime/p2p_local_{kind}"


def runtime_arn(kind: str) -> str:
    return _ARN_TMPL.format(region=REGION, kind=kind)


def endpoint_env() -> dict[str, str]:
    """The AWS_ENDPOINT_URL_* overrides that reroute app code to local infra.

    Bedrock (``bedrock-runtime``) is intentionally omitted so Strands agent model
    calls resolve to real AWS. ``bedrock-agentcore`` covers both the Runtime
    data plane (InvokeAgentRuntime) and Memory (create/list_events), which the
    shim serves on one port.
    """
    moto = f"http://127.0.0.1:{MOTO_PORT}"
    return {
        "AWS_ENDPOINT_URL_DYNAMODB": moto,
        "AWS_ENDPOINT_URL_S3": moto,
        "AWS_ENDPOINT_URL_SECRETS_MANAGER": moto,
        "AWS_ENDPOINT_URL_BEDROCK_AGENTCORE": f"http://127.0.0.1:{AGENTCORE_SHIM_PORT}",
    }


def app_env() -> dict[str, str]:
    """Environment the backend + agents run with (app code reads these).

    Mirrors the deployed env vars (table prefix, bucket, gateway endpoint, agent
    runtime ARNs) so the unmodified application wires itself to local infra.
    """
    env = {
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
        "AWS_REGION_NAME": REGION,
        "DEPLOYMENT_ENV": "local",
        "DYNAMODB_TABLE_PREFIX": TABLE_PREFIX,
        "S3_BUCKET": S3_BUCKET,
        "ERPNEXT_URL": ERPNEXT_URL,
        "ERPNEXT_SECRET_NAME": ERPNEXT_SECRET_NAME,
        "GATEWAY_ENDPOINT": f"http://127.0.0.1:{MCP_GATEWAY_PORT}/mcp",
        # AgentCore Memory: a fixed local memory id keeps chat history working
        # against the memory shim (create/list_events).
        "BEDROCK_AGENTCORE_MEMORY_ID": os.environ.get(
            "BEDROCK_AGENTCORE_MEMORY_ID", "p2p_local_memory-000000"
        ),
    }
    for kind, port in AGENT_PORTS.items():
        env[f"VITE_AGENTCORE_{kind.upper()}_ARN"] = runtime_arn(kind)
        env[f"AGENTCORE_{kind.upper()}_ARN"] = runtime_arn(kind)
        # The agentcore runtime shim + agent-proxy resolve a kind -> local port
        # through these; every process needs them, not just the agent itself.
        env[f"ARIA_AGENT_{kind.upper()}_PORT"] = str(port)
    env["ARIA_AGENTCORE_SHIM_PORT"] = str(AGENTCORE_SHIM_PORT)
    env["ARIA_AGENT_PROXY_PORT"] = str(AGENT_PROXY_PORT)
    env["ARIA_CANONICAL_API_PORT"] = str(CANONICAL_API_PORT)
    env["ARIA_MCP_GATEWAY_PORT"] = str(MCP_GATEWAY_PORT)
    env["ARIA_MOTO_PORT"] = str(MOTO_PORT)
    env.update(endpoint_env())
    return env
