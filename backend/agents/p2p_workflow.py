# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
P2P Multi-Agent Workflow — helper utilities.

The actual workflow orchestration runs in agentcore_app.py (_run_workflow),
which chains agents via MCP Gateway tools. This module provides shared
helper functions for text extraction and JSON parsing from agent responses.
"""

import json
import logging

logger = logging.getLogger("p2p.workflow")


def _extract_text(result) -> str:
    """Extract text from a Strands AgentResult."""
    text = ""
    if hasattr(result, "message") and result.message:
        content = result.message.get("content", [])
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text += block["text"]
    return text or str(result)


def _parse_json(text: str) -> dict:
    """Parse JSON from agent response text. Handles messy markdown output."""
    if not text:
        return {"raw_text": ""}

    # Try 1: Direct parse
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        logger.debug("Direct JSON parse failed; trying next strategy")

    # Try 2: Extract from ```json ... ``` block
    if "```json" in text:
        try:
            json_str = text.split("```json")[1].split("```")[0]
            return json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            logger.debug("Fenced ```json block parse failed; trying next strategy")

    # Try 3: Find the LARGEST {...} block (usually the main JSON response)
    candidates = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start:i + 1])
                start = -1

    candidates.sort(key=len, reverse=True)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and len(parsed) > 1:
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue

    return {"raw_text": text[:1000]}
