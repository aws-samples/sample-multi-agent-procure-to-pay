# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Exception handling framework for P2P agents.

Every agent failure must be:
1. Categorized (transient vs permanent, agent vs infrastructure)
2. Logged with full context
3. Surfaced to the user with a clear next action
4. Recoverable — either via retry or human fallback
"""

import logging
import traceback
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger("p2p.exceptions")


class ErrorSeverity(str, Enum):
    LOW = "LOW"          # Informational, agent recovered on its own
    MEDIUM = "MEDIUM"    # Agent couldn't complete, needs human review
    HIGH = "HIGH"        # Critical failure, workflow blocked
    CRITICAL = "CRITICAL"  # System-level failure, multiple workflows affected


class ErrorCategory(str, Enum):
    # Agent-level errors
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_HALLUCINATION = "AGENT_HALLUCINATION"
    AGENT_LOW_CONFIDENCE = "AGENT_LOW_CONFIDENCE"
    AGENT_TOOL_FAILURE = "AGENT_TOOL_FAILURE"

    # Guardrail errors
    GUARDRAIL_BLOCKED_INPUT = "GUARDRAIL_BLOCKED_INPUT"
    GUARDRAIL_BLOCKED_OUTPUT = "GUARDRAIL_BLOCKED_OUTPUT"
    GUARDRAIL_PII_DETECTED = "GUARDRAIL_PII_DETECTED"

    # Infrastructure errors
    BEDROCK_THROTTLED = "BEDROCK_THROTTLED"
    BEDROCK_UNAVAILABLE = "BEDROCK_UNAVAILABLE"
    TEXTRACT_FAILURE = "TEXTRACT_FAILURE"
    DYNAMO_ERROR = "DYNAMO_ERROR"
    S3_ERROR = "S3_ERROR"

    # Data errors
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    INVALID_DATA = "INVALID_DATA"
    MATCH_FAILURE = "MATCH_FAILURE"

    # Unknown
    UNKNOWN = "UNKNOWN"


class AgentError(BaseModel):
    """Structured error record for any agent failure."""
    error_id: str
    timestamp: str
    agent_name: str
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    document_id: Optional[str] = None  # BANFN, EBELN, BELNR, etc.
    document_type: Optional[str] = None  # PR, PO, GR, INVOICE
    retry_eligible: bool = False
    retries_attempted: int = 0
    max_retries: int = 3
    human_action_required: bool = False
    human_action_description: Optional[str] = None
    raw_error: Optional[str] = None
    resolved: bool = False
    resolved_by: Optional[str] = None
    resolved_at: Optional[str] = None


# --- Severity mapping by category ---

SEVERITY_MAP = {
    ErrorCategory.AGENT_TIMEOUT: ErrorSeverity.MEDIUM,
    ErrorCategory.AGENT_HALLUCINATION: ErrorSeverity.HIGH,
    ErrorCategory.AGENT_LOW_CONFIDENCE: ErrorSeverity.LOW,
    ErrorCategory.AGENT_TOOL_FAILURE: ErrorSeverity.MEDIUM,
    ErrorCategory.GUARDRAIL_BLOCKED_INPUT: ErrorSeverity.MEDIUM,
    ErrorCategory.GUARDRAIL_BLOCKED_OUTPUT: ErrorSeverity.MEDIUM,
    ErrorCategory.GUARDRAIL_PII_DETECTED: ErrorSeverity.HIGH,
    ErrorCategory.BEDROCK_THROTTLED: ErrorSeverity.LOW,
    ErrorCategory.BEDROCK_UNAVAILABLE: ErrorSeverity.CRITICAL,
    ErrorCategory.TEXTRACT_FAILURE: ErrorSeverity.MEDIUM,
    ErrorCategory.DYNAMO_ERROR: ErrorSeverity.HIGH,
    ErrorCategory.S3_ERROR: ErrorSeverity.HIGH,
    ErrorCategory.DOCUMENT_NOT_FOUND: ErrorSeverity.MEDIUM,
    ErrorCategory.INVALID_DATA: ErrorSeverity.MEDIUM,
    ErrorCategory.MATCH_FAILURE: ErrorSeverity.LOW,
    ErrorCategory.UNKNOWN: ErrorSeverity.HIGH,
}

RETRYABLE = {
    ErrorCategory.BEDROCK_THROTTLED,
    ErrorCategory.BEDROCK_UNAVAILABLE,
    ErrorCategory.AGENT_TIMEOUT,
    ErrorCategory.TEXTRACT_FAILURE,
    ErrorCategory.DYNAMO_ERROR,
    ErrorCategory.S3_ERROR,
}


def classify_error(exception: Exception, agent_name: str) -> ErrorCategory:
    """Classify an exception into an error category."""
    error_str = str(exception).lower()
    exc_type = type(exception).__name__

    # Bedrock / model errors
    if "throttl" in error_str or "rate" in error_str:
        return ErrorCategory.BEDROCK_THROTTLED
    if "bedrock" in error_str and ("unavailable" in error_str or "service" in error_str):
        return ErrorCategory.BEDROCK_UNAVAILABLE
    if "timeout" in error_str or "timed out" in error_str:
        return ErrorCategory.AGENT_TIMEOUT

    # Guardrail errors
    if "guardrail" in error_str or "blocked" in error_str:
        if "input" in error_str:
            return ErrorCategory.GUARDRAIL_BLOCKED_INPUT
        if "pii" in error_str or "sensitive" in error_str:
            return ErrorCategory.GUARDRAIL_PII_DETECTED
        return ErrorCategory.GUARDRAIL_BLOCKED_OUTPUT

    # AWS service errors
    if "textract" in error_str:
        return ErrorCategory.TEXTRACT_FAILURE
    if "dynamodb" in error_str or exc_type == "ClientError" and "dynamo" in error_str:
        return ErrorCategory.DYNAMO_ERROR
    if "s3" in error_str or "nosuchkey" in error_str:
        return ErrorCategory.S3_ERROR
    if "not found" in error_str or "does not exist" in error_str:
        return ErrorCategory.DOCUMENT_NOT_FOUND

    return ErrorCategory.UNKNOWN


def create_agent_error(
    exception: Exception,
    agent_name: str,
    document_id: str = None,
    document_type: str = None,
) -> AgentError:
    """Create a structured error record from an exception."""
    import uuid

    category = classify_error(exception, agent_name)
    severity = SEVERITY_MAP.get(category, ErrorSeverity.HIGH)
    retry_eligible = category in RETRYABLE

    # Determine if human action is needed
    human_needed = severity in (ErrorSeverity.HIGH, ErrorSeverity.CRITICAL) and not retry_eligible
    human_desc = None
    if human_needed:
        human_desc = _human_action_for(category, document_type, document_id)

    error = AgentError(
        error_id=str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
        agent_name=agent_name,
        category=category,
        severity=severity,
        message=str(exception),
        document_id=document_id,
        document_type=document_type,
        retry_eligible=retry_eligible,
        human_action_required=human_needed,
        human_action_description=human_desc,
        raw_error=traceback.format_exc(),
    )

    # Log it
    log_fn = logger.warning if severity in (ErrorSeverity.LOW, ErrorSeverity.MEDIUM) else logger.error
    log_fn(
        f"[{agent_name}] {category.value} — {exception} "
        f"(doc={document_type}:{document_id}, severity={severity.value}, retry={retry_eligible})"
    )

    return error


def _human_action_for(category: ErrorCategory, doc_type: str, doc_id: str) -> str:
    """Generate a human-readable action description."""
    doc_ref = f"{doc_type} {doc_id}" if doc_type and doc_id else "the document"

    actions = {
        ErrorCategory.AGENT_HALLUCINATION: f"Review agent output for {doc_ref}. The agent may have generated incorrect data.",
        ErrorCategory.GUARDRAIL_PII_DETECTED: f"Review {doc_ref} for sensitive data that triggered the guardrail. Remove or redact before reprocessing.",
        ErrorCategory.GUARDRAIL_BLOCKED_INPUT: f"Review the input for {doc_ref}. Content was blocked by the guardrail.",
        ErrorCategory.GUARDRAIL_BLOCKED_OUTPUT: f"Review agent response for {doc_ref}. Output was blocked by the guardrail.",
        ErrorCategory.DYNAMO_ERROR: f"Database error processing {doc_ref}. Check DynamoDB table health and retry.",
        ErrorCategory.S3_ERROR: f"Storage error for {doc_ref}. Verify the document exists in S3.",
        ErrorCategory.DOCUMENT_NOT_FOUND: f"{doc_ref} was not found. Verify the document ID and retry.",
        ErrorCategory.INVALID_DATA: f"Data validation failed for {doc_ref}. Review the document data and correct.",
    }
    return actions.get(category, f"Manual review required for {doc_ref}.")
