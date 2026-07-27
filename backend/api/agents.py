# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Agent API routes — chat endpoint.

Specialized agents (requisition, sourcing, PO, receiving, invoice, payment)
run on AgentCore Runtime. The frontend invokes them directly via SigV4-signed
requests using Cognito Identity Pool credentials.

The chat agent runs synchronously on Lambda since it's conversational.
"""

import json
import logging
from fastapi import APIRouter, Request
from services.rate_limiter import check_agent_rate_limit, get_rate_limit_status
from services.auth import get_authenticated_user

router = APIRouter()
logger = logging.getLogger("p2p.agents.api")


@router.get("/rate-limit")
def rate_limit_status(request: Request):
    user = get_authenticated_user(request) or "anonymous"
    return get_rate_limit_status(user)


@router.post("/chat")
def agent_chat(body: dict, request: Request):
    from agents.chat_agent import invoke as chat_invoke
    from services.auth import get_user_email, get_user_department
    user_email = get_user_email(request)
    user_department = get_user_department(request)
    session_id = body.get("session_id", "")

    message = body.get("message", "")
    result = chat_invoke(
        message=message,
        role=body.get("role", "admin"),
        role_context=body.get("role_context", ""),
        conversation_history=body.get("conversation_history", []),
        user_email=user_email,
        user_department=user_department or "",
    )

    # Persist messages to AgentCore Memory (server-side) + ensure DDB session pointer exists
    generated_title = None
    if session_id and user_email:
        try:
            from api.chat import (
                _email_to_actor, _store_message, _load_messages,
                _get_sessions, _save_sessions,
                generate_title, update_session_title,
            )
            from datetime import datetime
            actor_id = _email_to_actor(user_email)

            # Store conversation turns in AgentCore Memory (the only message store)
            _store_message(actor_id, session_id, "user", message)
            response_text = result.get("response", "") if isinstance(result, dict) else ""
            if response_text:
                _store_message(actor_id, session_id, "assistant", response_text)

            # Ensure DDB has a session pointer (no message content — just ID + title)
            sessions = _get_sessions(user_email)
            if not any(s["id"] == session_id for s in sessions):
                sessions = [{"id": session_id, "title": message[:40], "created_at": datetime.utcnow().isoformat()}] + sessions
                _save_sessions(user_email, sessions)

            # Auto-generate title with Haiku after 2nd user message
            all_messages = _load_messages(actor_id, session_id)
            user_msg_count = sum(1 for m in all_messages if m.get("role") == "user")
            if user_msg_count in (2, 3):
                new_title = generate_title(all_messages)
                if new_title:
                    update_session_title(user_email, session_id, new_title)
                    generated_title = new_title
        except Exception as e:
            logger.warning("Failed to persist chat to memory: %s", e)

    if generated_title and isinstance(result, dict):
        result["generated_title"] = generated_title
    return result
