# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Tests for backend service modules.

Covers: dynamo, auth, rate_limiter, exceptions.
"""

import os
import sys
import time
import uuid
import json
import base64
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

import boto3
import pytest
from moto import mock_aws
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers — table creation
# ---------------------------------------------------------------------------

PREFIX = os.environ.get("DYNAMODB_TABLE_PREFIX", "p2p-test")


def _create_tables_with_indexes(dynamodb):
    """Create DynamoDB tables used by the current backend."""
    simple = {
        f"{PREFIX}-agent-decisions": "decision_id",
        f"{PREFIX}-agent-errors": "error_id",
        f"{PREFIX}-agent-jobs": "job_id",
    }
    for table_name, pk in simple.items():
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )


@pytest.fixture
def dynamo():
    """Provide moto DynamoDB with all tables required by service modules."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables_with_indexes(dynamodb)
        yield dynamodb


# =========================================================================
# 1. DynamoDB helper (services/dynamo.py)
# =========================================================================

class TestDynamoHelper:
    """Tests for services.dynamo — low-level CRUD wrapper."""

    def test_put_and_get_item(self, dynamo):
        """put_item stores an item retrievable by get_item."""
        import services.dynamo as svc
        svc.dynamodb = dynamo

        item = {"job_id": "JOB-001", "status": "DRAFT", "total": Decimal("100")}
        svc.put_item("agent-jobs", item)

        result = svc.get_item("agent-jobs", {"job_id": "JOB-001"})
        assert result is not None
        assert result["status"] == "DRAFT"
        assert result["total"] == Decimal("100")

    def test_get_item_missing_returns_none(self, dynamo):
        """get_item returns None when key does not exist."""
        import services.dynamo as svc
        svc.dynamodb = dynamo

        result = svc.get_item("agent-jobs", {"job_id": "NONEXISTENT"})
        assert result is None

    def test_update_item(self, dynamo):
        """update_item changes attributes and returns ALL_NEW."""
        import services.dynamo as svc
        svc.dynamodb = dynamo

        svc.put_item("agent-jobs", {"job_id": "JOB-002", "status": "DRAFT"})
        updated = svc.update_item(
            "agent-jobs",
            {"job_id": "JOB-002"},
            {"status": "APPROVED", "approved_by": "alice"},
        )
        assert updated["status"] == "APPROVED"
        assert updated["approved_by"] == "alice"
        assert updated["job_id"] == "JOB-002"

    def test_scan_table_returns_all(self, dynamo):
        """scan_table returns every item in the table."""
        import services.dynamo as svc
        svc.dynamodb = dynamo

        svc.put_item("agent-jobs", {"job_id": "JOB-A", "kind": "PR"})
        svc.put_item("agent-jobs", {"job_id": "JOB-B", "kind": "PO"})
        items = svc.scan_table("agent-jobs")
        assert len(items) == 2

    def test_scan_table_empty(self, dynamo):
        """scan_table on an empty table returns []."""
        import services.dynamo as svc
        svc.dynamodb = dynamo

        items = svc.scan_table("agent-jobs")
        assert items == []

    def test_get_table_applies_prefix(self, dynamo):
        """get_table prepends the configured table prefix."""
        import services.dynamo as svc
        svc.dynamodb = dynamo

        table = svc.get_table("agent-jobs")
        assert table.name == f"{PREFIX}-agent-jobs"


# =========================================================================
# 2. Auth (services/auth.py)
# =========================================================================

class TestAuth:
    """Tests for JWT extraction and authentication middleware."""

    def _make_request(self, headers=None, claims=None):
        req = MagicMock()
        req.headers = headers or {}
        req.scope = {}
        if claims is not None:
            # API Gateway HTTP API (v2) event shape, as Mangum puts it on the scope.
            req.scope["aws.event"] = {
                "version": "2.0",
                "requestContext": {"authorizer": {"jwt": {"claims": claims}}},
            }
        return req

    def _make_jwt(self, claims: dict) -> str:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        return f"{header}.{payload}.fakesig"

    def test_ignores_x_amz_user_header(self):
        """Any client can set this header, so it must not authenticate anyone."""
        from services.auth import get_authenticated_user
        req = self._make_request(headers={"x-amz-user": "test.user"})
        assert get_authenticated_user(req) is None

    def test_extract_from_jwt_cognito_username(self):
        from services.auth import get_authenticated_user
        token = self._make_jwt({"cognito:username": "sarah.johnson"})
        req = self._make_request(headers={"authorization": f"Bearer {token}"})
        assert get_authenticated_user(req) == "sarah.johnson"

    def test_extract_from_jwt_sub_claim(self):
        from services.auth import get_authenticated_user
        token = self._make_jwt({"sub": "abc-123-def"})
        req = self._make_request(headers={"authorization": f"Bearer {token}"})
        assert get_authenticated_user(req) == "abc-123-def"

    def test_returns_none_when_no_auth(self):
        from services.auth import get_authenticated_user
        req = self._make_request(headers={})
        assert get_authenticated_user(req) is None

    def test_returns_none_for_malformed_bearer(self):
        from services.auth import get_authenticated_user
        req = self._make_request(headers={"authorization": "Bearer not.valid"})
        assert get_authenticated_user(req) is None

    def test_extract_from_api_gateway_context(self):
        from services.auth import get_authenticated_user
        req = self._make_request(claims={"cognito:username": "api-gw-user"})
        assert get_authenticated_user(req) == "api-gw-user"

    def test_email_comes_from_verified_claims(self):
        from services.auth import get_user_email
        req = self._make_request(claims={"email": "maria@example.com"})
        assert get_user_email(req) == "maria@example.com"

    def test_email_ignores_client_supplied_header(self):
        """x-p2p-user-email selects per-user ERPNext credentials downstream, so
        trusting it would let any caller act as another user."""
        from services.auth import get_user_email
        req = self._make_request(
            headers={"x-p2p-user-email": "administrator@example.com"},
            claims={"email": "maria@example.com"},
        )
        assert get_user_email(req) == "maria@example.com"

    def test_department_comes_from_verified_claims(self):
        from services.auth import get_user_department
        req = self._make_request(claims={"custom:department": "Manufacturing"})
        assert get_user_department(req) == "Manufacturing"


# =========================================================================
# 3. Rate Limiter (services/rate_limiter.py)
# =========================================================================

class TestRateLimiter:
    """Tests for per-user token-bucket rate limiting."""

    def _reset_buckets(self):
        from services import rate_limiter
        rate_limiter._buckets.clear()
        return rate_limiter

    def test_allows_calls_within_limit(self):
        rl = self._reset_buckets()
        for _ in range(rl.AGENT_RATE_LIMIT):
            rl.check_agent_rate_limit("user-ok")

    def test_raises_429_when_exceeded(self):
        rl = self._reset_buckets()
        for _ in range(rl.AGENT_RATE_LIMIT):
            rl.check_agent_rate_limit("user-flood")
        with pytest.raises(HTTPException) as exc_info:
            rl.check_agent_rate_limit("user-flood")
        assert exc_info.value.status_code == 429

    def test_status_reports_remaining(self):
        rl = self._reset_buckets()
        rl.check_agent_rate_limit("user-status")
        status = rl.get_rate_limit_status("user-status")
        assert status["used"] == 1
        assert status["remaining"] == rl.AGENT_RATE_LIMIT - 1

    def test_expired_entries_are_pruned(self):
        rl = self._reset_buckets()
        old_time = time.time() - rl.AGENT_RATE_WINDOW - 10
        rl._buckets["user-old"] = [old_time] * rl.AGENT_RATE_LIMIT
        rl.check_agent_rate_limit("user-old")
        status = rl.get_rate_limit_status("user-old")
        assert status["used"] == 1

    def test_separate_users_have_separate_limits(self):
        rl = self._reset_buckets()
        for _ in range(rl.AGENT_RATE_LIMIT):
            rl.check_agent_rate_limit("user-a")
        rl.check_agent_rate_limit("user-b")
        assert rl.get_rate_limit_status("user-b")["used"] == 1


# =========================================================================
# 4. Exceptions (services/exceptions.py)
# =========================================================================

class TestExceptions:
    """Tests for error classification and structured AgentError creation."""

    def test_classify_throttle_error(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Rate throttled by Bedrock"), "test_agent")
        assert cat == ErrorCategory.BEDROCK_THROTTLED

    def test_classify_timeout_error(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Request timed out"), "test_agent")
        assert cat == ErrorCategory.AGENT_TIMEOUT

    def test_classify_guardrail_input_error(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Guardrail blocked the input"), "test_agent")
        assert cat == ErrorCategory.GUARDRAIL_BLOCKED_INPUT

    def test_classify_guardrail_pii_error(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Guardrail: PII/sensitive data detected"), "test_agent")
        assert cat == ErrorCategory.GUARDRAIL_PII_DETECTED

    def test_classify_document_not_found(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Document does not exist"), "test_agent")
        assert cat == ErrorCategory.DOCUMENT_NOT_FOUND

    def test_classify_unknown_error(self):
        from services.exceptions import classify_error, ErrorCategory
        cat = classify_error(Exception("Something truly bizarre"), "test_agent")
        assert cat == ErrorCategory.UNKNOWN

    def test_create_agent_error_structure(self):
        from services.exceptions import create_agent_error, ErrorCategory, ErrorSeverity
        exc = Exception("Rate throttled by Bedrock")
        err = create_agent_error(exc, "requisition_agent", "PR-100", "PR")

        assert err.agent_name == "requisition_agent"
        assert err.category == ErrorCategory.BEDROCK_THROTTLED
        assert err.severity == ErrorSeverity.LOW
        assert err.retry_eligible is True
        assert err.document_id == "PR-100"
        assert err.error_id

    def test_create_agent_error_non_retryable(self):
        from services.exceptions import create_agent_error, ErrorCategory
        exc = Exception("Something truly bizarre happened")
        err = create_agent_error(exc, "sourcing_agent", "SR-200", "PR")

        assert err.category == ErrorCategory.UNKNOWN
        assert err.retry_eligible is False
        assert err.human_action_required is True

    def test_create_agent_error_human_action_for_pii(self):
        from services.exceptions import create_agent_error, ErrorCategory
        exc = Exception("Guardrail: PII/sensitive data blocked")
        err = create_agent_error(exc, "invoice_agent", "INV-300", "INVOICE")

        assert err.category == ErrorCategory.GUARDRAIL_PII_DETECTED
        assert err.human_action_required is True

    def test_severity_map_completeness(self):
        from services.exceptions import ErrorCategory, SEVERITY_MAP
        for cat in ErrorCategory:
            assert cat in SEVERITY_MAP, f"Missing severity mapping for {cat}"

    def test_retryable_categories(self):
        from services.exceptions import RETRYABLE, ErrorCategory
        expected_retryable = {
            ErrorCategory.BEDROCK_THROTTLED,
            ErrorCategory.BEDROCK_UNAVAILABLE,
            ErrorCategory.AGENT_TIMEOUT,
            ErrorCategory.TEXTRACT_FAILURE,
            ErrorCategory.DYNAMO_ERROR,
            ErrorCategory.S3_ERROR,
        }
        assert RETRYABLE == expected_retryable
