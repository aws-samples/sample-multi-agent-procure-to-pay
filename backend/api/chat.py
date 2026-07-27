# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Chat session persistence API.

Messages stored in AgentCore Memory (short-term memory).
Session index (titles, timestamps) stored in DynamoDB for listing.

AgentCore Memory API:
  - create_event(memoryId, actorId, sessionId, payload) → store conversation turn
  - list_events(memoryId, actorId, sessionId) → retrieve session messages
  - delete_event(memoryId, actorId, sessionId, eventId) → remove an event
"""

import os
import logging
from datetime import datetime
from typing import Optional

import boto3
from fastapi import APIRouter, Header
from pydantic import BaseModel

from services.dynamo import get_item, put_item, get_table

router = APIRouter()
logger = logging.getLogger("p2p.chat")

MEMORY_ID = os.environ.get("BEDROCK_AGENTCORE_MEMORY_ID", "")
REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-east-1"))
# DDB table for session index only (list of {id, title} per user).
# All message content is stored in AgentCore Memory, not DDB.
SESSION_TABLE = "chat-sessions"


def _memory_client():
    return boto3.client("bedrock-agentcore", region_name=REGION)


class ChatMessageIn(BaseModel):
    session_id: str
    role: str  # "user" or "assistant"
    content: str
    tools_used: list[str] = []


class ChatSessionCreate(BaseModel):
    session_id: str
    title: str


# ── Actor ID helper ─────────────────────────────────────────────────────────
# AgentCore actorId: [a-zA-Z0-9][a-zA-Z0-9-_/]*


def _email_to_actor(email: str) -> str:
    """Convert email to a valid actorId (no +@. characters)."""
    return email.replace("+", "-").replace("@", "-at-").replace(".", "-")


def _resolve_email(authorization: Optional[str]) -> str:
    """Extract user email from JWT token (payload decode, no verification)."""
    if not authorization or not authorization.startswith("Bearer "):
        return "anonymous"
    try:
        import base64, json as _json
        token = authorization.split(" ")[1]
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = _json.loads(base64.b64decode(payload))
        return claims.get("email", "anonymous")
    except Exception:
        return "anonymous"


# ── Session index (DynamoDB) ────────────────────────────────────────────────


def _get_sessions(email: str) -> list[dict]:
    item = get_item(SESSION_TABLE, {"user_id": email})
    if not item:
        return []
    return item.get("sessions", [])


def _save_sessions(email: str, sessions: list[dict]):
    put_item(SESSION_TABLE, {
        "user_id": email,
        "sessions": sessions[:30],
        "updated_at": datetime.utcnow().isoformat(),
    })


def update_session_title(email: str, session_id: str, new_title: str):
    """Update the title of a specific session in the DDB session index."""
    sessions = _get_sessions(email)
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = new_title
            break
    _save_sessions(email, sessions)


def generate_title(messages: list[dict]) -> str:
    """Call Haiku 4.5 to generate a 3-5 word conversation title.

    Returns empty string on failure (caller should keep the existing title).
    """
    try:
        client = boto3.client("bedrock-runtime", region_name=REGION)
        convo = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')[:200]}"
            for m in messages[-6:]
        )
        resp = client.converse(
            modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
            messages=[{
                "role": "user",
                "content": [{"text": (
                    "Generate a 3-5 word title for this conversation. "
                    "Reply with ONLY the title, nothing else.\n\n" + convo
                )}],
            }],
            inferenceConfig={"maxTokens": 30, "temperature": 0.0},
        )
        title = resp["output"]["message"]["content"][0]["text"].strip().strip('"\'')
        return title if 0 < len(title) <= 60 else ""
    except Exception as e:
        logger.warning("Title generation failed: %s", e)
        return ""


# ── AgentCore Memory helpers ────────────────────────────────────────────────


def _store_message(actor_id: str, session_id: str, role: str, content: str):
    """Store a single conversation turn in AgentCore Memory."""
    if not MEMORY_ID:
        logger.warning("BEDROCK_AGENTCORE_MEMORY_ID not set — skipping memory write")
        return

    try:
        client = _memory_client()
        client.create_event(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=datetime.utcnow(),
            payload=[{
                "conversational": {
                    "content": {"text": content},
                    "role": "USER" if role == "user" else "ASSISTANT",
                }
            }],
        )
    except Exception as e:
        logger.error("Failed to store message in AgentCore Memory: %s", e)


def _load_messages(actor_id: str, session_id: str) -> list[dict]:
    """Load all messages for a session from AgentCore Memory."""
    if not MEMORY_ID:
        return []

    try:
        client = _memory_client()
        resp = client.list_events(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
        )
        messages = []
        for event in resp.get("events", []):
            for item in event.get("payload", []):
                conv = item.get("conversational", {})
                if conv:
                    role_raw = conv.get("role", "USER")
                    messages.append({
                        "role": "user" if role_raw == "USER" else "assistant",
                        "content": conv.get("content", {}).get("text", ""),
                        "timestamp": event.get("eventTimestamp", ""),
                        "tools_used": [],
                    })
        # Sort chronologically (AgentCore Memory may return newest-first)
        messages.sort(key=lambda m: m.get("timestamp", ""))
        return messages
    except Exception as e:
        logger.error("Failed to load messages from AgentCore Memory: %s", e)
        return []


def _delete_session_events(actor_id: str, session_id: str):
    """Delete all events for a session from AgentCore Memory."""
    if not MEMORY_ID:
        return

    try:
        client = _memory_client()
        resp = client.list_events(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
        )
        for event in resp.get("events", []):
            try:
                client.delete_event(
                    memoryId=MEMORY_ID,
                    actorId=actor_id,
                    sessionId=session_id,
                    eventId=event["eventId"],
                )
            except Exception:
                pass  # nosec B110 -- per-event delete is best-effort; outer try logs failures
    except Exception as e:
        logger.error("Failed to delete session events: %s", e)


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/sessions")
def list_sessions(authorization: Optional[str] = Header(None)):
    """List chat sessions for the current user."""
    email = _resolve_email(authorization)
    sessions = _get_sessions(email)
    return {"sessions": sessions, "user": email}


@router.post("/sessions")
def create_session(data: ChatSessionCreate, authorization: Optional[str] = Header(None)):
    """Create a new chat session."""
    email = _resolve_email(authorization)
    sessions = _get_sessions(email)

    new_session = {
        "id": data.session_id,
        "title": data.title,
        "created_at": datetime.utcnow().isoformat(),
    }

    sessions = [new_session] + [s for s in sessions if s["id"] != data.session_id]
    _save_sessions(email, sessions)

    return new_session


@router.get("/sessions/{session_id}")
def get_session_messages(session_id: str, authorization: Optional[str] = Header(None)):
    """Get all messages for a chat session from AgentCore Memory."""
    email = _resolve_email(authorization)
    actor_id = _email_to_actor(email)
    messages = _load_messages(actor_id, session_id)
    return {"session_id": session_id, "messages": messages}


@router.post("/message")
def save_message(data: ChatMessageIn, authorization: Optional[str] = Header(None)):
    """Save a chat message to AgentCore Memory. DDB is not updated — it's just a session pointer."""
    email = _resolve_email(authorization)
    actor_id = _email_to_actor(email)

    # Store in AgentCore Memory (the only message store)
    _store_message(actor_id, data.session_id, data.role, data.content)

    return {"status": "saved", "store": "agentcore_memory"}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, authorization: Optional[str] = Header(None)):
    """Delete a chat session from both Memory and DynamoDB index."""
    email = _resolve_email(authorization)
    actor_id = _email_to_actor(email)

    # Remove from session index
    sessions = _get_sessions(email)
    sessions = [s for s in sessions if s["id"] != session_id]
    _save_sessions(email, sessions)

    # Delete events from AgentCore Memory
    _delete_session_events(actor_id, session_id)

    return {"status": "deleted"}
