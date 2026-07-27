# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Local stand-in for the AgentCore data plane (Runtime + Memory).

Both AgentCore APIs the app uses are plain ``rest-json`` REST calls with no local
emulator, but botocore resolves ``bedrock-agentcore`` against
``AWS_ENDPOINT_URL_BEDROCK_AGENTCORE`` — so pointing that env var here reroutes
the unmodified application code (backend/utils/mcp_client.py, backend/api/chat.py,
frontend agent calls proxied through the backend) with no code change.

Two contracts are reproduced (URIs verified from the botocore service model):

  Runtime (InvokeAgentRuntime):
    POST /runtimes/{agentRuntimeArn}/invocations
      header  X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <session>
      body    <payload>  ->  streamed/blob response from the agent
    The ARN's trailing token carries the agent kind (p2p_local_<kind>); the shim
    maps kind -> the local agent's port and forwards. Each agent is a
    BedrockAgentCoreApp serving POST /invocations on its own port.

  Memory (create/list/delete event) — an in-process store keyed by
    (memoryId, actorId, sessionId):
    POST   /memories/{memoryId}/events                                  -> 201
    POST   /memories/{memoryId}/actor/{actorId}/sessions/{sessionId}    -> 200 (list)
    DELETE /memories/{memoryId}/actor/{actorId}/sessions/{sessionId}/events/{eventId}

Everything here is launcher-only and never ships deployed.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s agentcore-shim %(message)s"
)
logger = logging.getLogger("agentcore_shim")

_SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"

# Agent kinds — match the runtime ARN suffix (p2p_local_<kind>). Longest-first so
# compound kinds (po_management, invoice_matching) win over any prefix overlap.
_AGENT_KINDS = [
    "requisition",
    "sourcing",
    "po_management",
    "receiving",
    "invoice_matching",
    "payment",
    "workflow",
]
_KINDS_LONGEST_FIRST = sorted(_AGENT_KINDS, key=len, reverse=True)

# A generous timeout: a full agent run does real Bedrock calls inline.
_FORWARD_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _agent_port(kind: str) -> str | None:
    return os.environ.get(f"ARIA_AGENT_{kind.upper()}_PORT")


def _kind_from_arn(arn: str) -> str | None:
    resource = arn.rsplit("/", 1)[-1] if arn else ""
    for kind in _KINDS_LONGEST_FIRST:
        if re.search(rf"(?:^|_){re.escape(kind)}(?:$|_|-)", resource):
            return kind
    return None


# ── Runtime: forward to the local agent process ─────────────────────────────

async def invoke_runtime(request: Request) -> Response:
    raw_arn = request.path_params["arn"]
    arn = raw_arn.replace("%3A", ":").replace("%3a", ":")
    session_id = request.headers.get(_SESSION_HEADER, "")
    body = await request.body()

    kind = _kind_from_arn(arn)
    if kind is None:
        logger.error("Could not map ARN to an agent kind: %r", arn)
        return JSONResponse({"message": f"No local agent for ARN {arn!r}"}, status_code=404)

    port = _agent_port(kind)
    if not port:
        logger.error("No port configured for agent kind %r", kind)
        return JSONResponse({"message": f"Agent {kind} has no local port"}, status_code=502)

    target = f"http://127.0.0.1:{port}/invocations"
    logger.info("invoke -> %s (kind=%s session=%s)", target, kind, session_id[:16])
    try:
        async with httpx.AsyncClient(timeout=_FORWARD_TIMEOUT) as client:
            upstream = await client.post(
                target,
                content=body,
                headers={"Content-Type": request.headers.get("Content-Type", "application/json")},
            )
    except httpx.ConnectError:
        logger.error("Agent %s not reachable at %s", kind, target)
        return JSONResponse({"message": f"Agent {kind} not reachable"}, status_code=502)
    except httpx.TimeoutException:
        logger.error("Agent %s timed out", kind)
        return JSONResponse({"message": f"Agent {kind} timed out"}, status_code=504)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
        headers={_SESSION_HEADER: session_id},
    )


# ── Memory: in-process event store ──────────────────────────────────────────
# _STORE[(memoryId, actorId, sessionId)] -> list of event dicts (chronological).
_STORE: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
_seq = 0


def _next_event_id() -> str:
    global _seq
    _seq += 1
    return f"local-event-{_seq:08d}"


async def create_event(request: Request) -> Response:
    memory_id = request.path_params["memoryId"]
    payload = await request.json()
    actor_id = payload.get("actorId", "")
    session_id = payload.get("sessionId", "")
    event = {
        "eventId": _next_event_id(),
        "memoryId": memory_id,
        "actorId": actor_id,
        "sessionId": session_id,
        "eventTimestamp": payload.get("eventTimestamp", ""),
        "payload": payload.get("payload", []),
    }
    _STORE[(memory_id, actor_id, session_id)].append(event)
    return JSONResponse({"event": event}, status_code=201)


async def list_events(request: Request) -> Response:
    key = (
        request.path_params["memoryId"],
        request.path_params["actorId"],
        request.path_params["sessionId"],
    )
    return JSONResponse({"events": _STORE.get(key, [])}, status_code=200)


async def delete_event(request: Request) -> Response:
    key = (
        request.path_params["memoryId"],
        request.path_params["actorId"],
        request.path_params["sessionId"],
    )
    event_id = request.path_params["eventId"]
    _STORE[key] = [e for e in _STORE.get(key, []) if e["eventId"] != event_id]
    return JSONResponse({}, status_code=200)


async def healthz(_request: Request) -> Response:
    return JSONResponse({"ok": True, "shim": "agentcore"})


app = Starlette(
    routes=[
        Route("/runtimes/{arn:path}/invocations", invoke_runtime, methods=["POST"]),
        Route("/memories/{memoryId}/events", create_event, methods=["POST"]),
        Route(
            "/memories/{memoryId}/actor/{actorId}/sessions/{sessionId}",
            list_events,
            methods=["POST"],
        ),
        Route(
            "/memories/{memoryId}/actor/{actorId}/sessions/{sessionId}/events/{eventId}",
            delete_event,
            methods=["DELETE"],
        ),
        Route("/healthz", healthz, methods=["GET"]),
    ]
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("ARIA_AGENTCORE_SHIM_PORT", "9000"))
    logger.info("AgentCore shim (runtime + memory) listening on :%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
