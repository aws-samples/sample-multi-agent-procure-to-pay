# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Browser-facing proxy for agent invocations (local only).

In the cloud the SPA calls AgentCore Runtime directly from the browser with
SigV4-signed requests using Cognito Identity Pool credentials
(frontend/src/agentcore.ts). Locally there are no Cognito creds and the browser
cannot sign to the shim, so this proxy exposes a plain, unauthenticated endpoint
the SPA can hit in local mode:

    POST /local-agent/{agent_name}/invocations   body: {document_id, ...}
      -> streams the agent's NDJSON response back verbatim

It forwards to the AgentCore runtime shim (same path the real
InvokeAgentRuntime would take), so the full agent path — MCP tools, real
Bedrock, progress events — is exercised. CORS is open because the Vite dev
server serves the SPA from a different port.

Launcher-only; never ships deployed. The one matching frontend change is a
runtime-config branch in agentcore.ts gated on window.ARIA_CONFIG.localMode.
"""

from __future__ import annotations

import logging
import os

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s agent-proxy %(message)s"
)
logger = logging.getLogger("agent_proxy_shim")

_VALID = {
    "requisition", "sourcing", "po_management", "receiving",
    "invoice_matching", "payment", "workflow",
}
_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _shim_base() -> str:
    port = os.environ.get("ARIA_AGENTCORE_SHIM_PORT", "9000")
    return f"http://127.0.0.1:{port}"


def _runtime_arn(agent_name: str) -> str:
    region = os.environ.get("AWS_REGION", "us-east-1")
    return f"arn:aws:bedrock-agentcore:{region}:000000000000:runtime/p2p_local_{agent_name}"


async def invoke(request: Request) -> StreamingResponse | JSONResponse:
    agent_name = request.path_params["agent_name"]
    if agent_name not in _VALID:
        return JSONResponse({"error": f"unknown agent {agent_name!r}"}, status_code=404)

    body = await request.body()
    session_id = request.headers.get(
        "x-amzn-bedrock-agentcore-runtime-session-id", "session-local"
    )
    arn = _runtime_arn(agent_name)
    # botocore URL-encodes the ARN into the path; match that so the shim's
    # {arn:path} route + decode behave identically to the real call.
    from urllib.parse import quote
    url = f"{_shim_base()}/runtimes/{quote(arn, safe='')}/invocations?qualifier=DEFAULT"

    async def stream():
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream(
                "POST",
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
                },
            ) as upstream:
                async for chunk in upstream.aiter_bytes():
                    yield chunk

    logger.info("proxy invoke -> agent=%s session=%s", agent_name, session_id[:16])
    return StreamingResponse(stream(), media_type="application/x-ndjson")


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "shim": "agent-proxy"})


app = Starlette(
    routes=[
        Route("/local-agent/{agent_name}/invocations", invoke, methods=["POST"]),
        Route("/healthz", healthz, methods=["GET"]),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ],
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("ARIA_AGENT_PROXY_PORT", "8003"))
    logger.info("agent proxy shim listening on :%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
