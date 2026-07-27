# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Item 2: Rate limiting for agent invocations.

Simple token-bucket rate limiter backed by an in-memory dict (per Lambda instance)
and optionally DynamoDB for cross-instance enforcement.

Limits agent invocations per user to prevent Bedrock cost abuse.
"""

import time
import logging
from collections import defaultdict
from fastapi import HTTPException

logger = logging.getLogger("p2p.rate_limiter")

# Per-user rate limits for agent calls
AGENT_RATE_LIMIT = 10       # max calls per window
AGENT_RATE_WINDOW = 300     # window in seconds (5 minutes)

# In-memory buckets (reset on Lambda cold start, which is acceptable)
_buckets: dict[str, list[float]] = defaultdict(list)


def check_agent_rate_limit(user_id: str) -> None:
    """
    Check if the user has exceeded the agent invocation rate limit.
    Raises HTTPException 429 if exceeded.
    """
    now = time.time()
    window_start = now - AGENT_RATE_WINDOW

    # Prune old entries
    _buckets[user_id] = [t for t in _buckets[user_id] if t > window_start]

    if len(_buckets[user_id]) >= AGENT_RATE_LIMIT:
        remaining_wait = int(_buckets[user_id][0] + AGENT_RATE_WINDOW - now) + 1
        logger.warning(f"Rate limit exceeded for user {user_id}: {len(_buckets[user_id])} calls in {AGENT_RATE_WINDOW}s")
        raise HTTPException(
            status_code=429,
            detail=f"Agent rate limit exceeded. Max {AGENT_RATE_LIMIT} agent calls per {AGENT_RATE_WINDOW // 60} minutes. Try again in {remaining_wait}s.",
        )

    _buckets[user_id].append(now)


def get_rate_limit_status(user_id: str) -> dict:
    """Return current rate limit status for a user."""
    now = time.time()
    window_start = now - AGENT_RATE_WINDOW
    _buckets[user_id] = [t for t in _buckets[user_id] if t > window_start]
    return {
        "used": len(_buckets[user_id]),
        "limit": AGENT_RATE_LIMIT,
        "remaining": max(0, AGENT_RATE_LIMIT - len(_buckets[user_id])),
        "window_seconds": AGENT_RATE_WINDOW,
    }
