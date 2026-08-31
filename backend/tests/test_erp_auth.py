# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Authorization tests for the canonical ERP API.

These drive the Lambda entry point (`handler`) rather than a TestClient, because
the identity rules depend on the API Gateway event that Mangum puts on the ASGI
scope — which is exactly what a TestClient does not provide.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from adapters.canonical_api import Caller, _caller, _get_adapter, handler
from adapters.models import SupplierList, Supplier
from services import erp_client


def _apigw_event(path="/api/erp/suppliers", method="GET", claims=None, headers=None):
    """An API Gateway v2 event as it arrives from the public HTTP API."""
    request_context = {
        "http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.7"},
    }
    if claims is not None:
        request_context["authorizer"] = {"jwt": {"claims": claims}}

    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"accept": "application/json", "host": "api.example.com", **(headers or {})},
        "requestContext": request_context,
        "body": None,
        "isBase64Encoded": False,
    }


def _invoke(event):
    resp = handler(event, MagicMock(client_context=None))
    body = json.loads(resp["body"]) if resp.get("body") else {}
    return resp["statusCode"], body


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.list_suppliers.return_value = SupplierList(
        suppliers=[Supplier(supplier_id="SUP-001", supplier_name="Acme Corp")],
        total_count=1,
    )
    return adapter


class TestPublicRouteRequiresIdentity:
    """An internet request with no verified JWT identity must be rejected."""

    def test_no_authorizer_claims_is_401(self):
        status, body = _invoke(_apigw_event())
        assert status == 401
        assert "no verified user identity" in body["detail"]

    def test_empty_claims_is_401(self):
        status, _ = _invoke(_apigw_event(claims={}))
        assert status == 401

    def test_spoofed_email_header_alone_is_401(self):
        """The pre-fix escalation path: header without a JWT must not authenticate."""
        status, _ = _invoke(
            _apigw_event(headers={"x-p2p-user-email": "demo+agent@example.com"})
        )
        assert status == 401

    def test_health_needs_no_user_identity(self):
        """Health touches no ERP data, so it has no _caller dependency. API
        Gateway still fronts it with the JWT authorizer via /api/erp/{proxy+}."""
        status, body = _invoke(_apigw_event(path="/api/erp/health"))
        assert status == 200
        assert body["status"] == "ok"


class TestJwtClaimsWinOverHeader:
    def test_header_cannot_override_verified_claims(self, mock_adapter):
        """A caller may not act as someone else by setting x-p2p-user-email."""
        seen = []

        def _record(caller=None):
            seen.append(caller)
            return mock_adapter

        with patch("adapters.canonical_api._get_adapter", _record):
            status, _ = _invoke(_apigw_event(
                claims={"email": "maria@example.com"},
                headers={"x-p2p-user-email": "administrator@example.com"},
            ))

        assert status == 200
        assert seen[0].email == "maria@example.com"
        assert seen[0].allow_service_account is False

    def test_cognito_email_claim_is_accepted(self, mock_adapter):
        seen = []
        with patch("adapters.canonical_api._get_adapter",
                   lambda caller=None: (seen.append(caller), mock_adapter)[1]):
            status, _ = _invoke(_apigw_event(claims={"cognito:email": "jake@example.com"}))
        assert status == 200
        assert seen[0].email == "jake@example.com"


class TestInternalCaller:
    def test_internal_marker_grants_service_account(self, mock_adapter):
        seen = []
        event = erp_client._build_event("GET", "/suppliers", user_email="demo+maria@example.com")

        with patch("adapters.canonical_api._get_adapter",
                   lambda caller=None: (seen.append(caller), mock_adapter)[1]):
            status, body = _invoke(event)

        assert status == 200
        assert body["total_count"] == 1
        assert seen[0].email == "demo+maria@example.com"
        assert seen[0].allow_service_account is True

    def test_internal_event_routes_through_mangum_base_path(self, mock_adapter):
        """erp_client paths must survive Mangum's /api/erp base-path stripping."""
        with patch("adapters.canonical_api._get_adapter", lambda caller=None: mock_adapter):
            status, _ = _invoke(erp_client._build_event("GET", "/suppliers"))
        assert status == 200

    def test_internal_event_carries_query_string(self, mock_adapter):
        with patch("adapters.canonical_api._get_adapter", lambda caller=None: mock_adapter):
            status, _ = _invoke(erp_client._build_event(
                "GET", "/suppliers", params={"status": "active", "group": None},
            ))
        assert status == 200
        assert mock_adapter.list_suppliers.call_args.kwargs["status"] == "active"
        assert mock_adapter.list_suppliers.call_args.kwargs["group"] is None

    def test_internal_event_carries_json_body(self):
        event = erp_client._build_event("POST", "/payments", json_body={"invoice_id": "PINV-1"})
        assert json.loads(event["body"]) == {"invoice_id": "PINV-1"}
        assert event["headers"]["content-type"] == "application/json"

    def test_marker_lives_in_request_context_not_headers(self):
        """API Gateway builds requestContext, so a client cannot forge the marker."""
        event = erp_client._build_event("GET", "/suppliers")
        assert event["requestContext"][erp_client._INTERNAL_CALL_KEY] is True
        assert not any("internal" in k.lower() for k in event["headers"])


class TestGatewayToolCalls:
    def test_gateway_call_allows_service_account(self, mock_adapter):
        seen = []
        context = MagicMock()
        context.client_context.custom = {"bedrockAgentCoreToolName": "ERPTarget___list_suppliers"}

        with patch("adapters.canonical_api._get_adapter",
                   lambda caller=None: (seen.append(caller), mock_adapter)[1]):
            result = handler({"user_email": "priya@example.com"}, context)

        assert result["total_count"] == 1
        assert seen[0].email == "priya@example.com"
        assert seen[0].allow_service_account is True


class TestAdapterSelection:
    """_get_adapter fails closed rather than silently escalating."""

    def test_unprovisioned_user_gets_403(self):
        manager = MagicMock()
        manager.get_credentials_for_user.return_value = None

        with patch("adapters.canonical_api._get_token_manager", return_value=manager), \
             patch("adapters.canonical_api._build_service_adapter") as build:
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                _get_adapter(Caller(email="nobody@example.com"))

        assert exc.value.status_code == 403
        build.assert_not_called()

    def test_anonymous_caller_gets_401(self):
        from fastapi import HTTPException
        with patch("adapters.canonical_api._build_service_adapter") as build:
            with pytest.raises(HTTPException) as exc:
                _get_adapter(Caller())
        assert exc.value.status_code == 401
        build.assert_not_called()

    def test_no_caller_argument_gets_401(self):
        """The default must be deny — a missed call site cannot escalate."""
        from fastapi import HTTPException
        with patch("adapters.canonical_api._build_service_adapter") as build:
            with pytest.raises(HTTPException) as exc:
                _get_adapter()
        assert exc.value.status_code == 401
        build.assert_not_called()

    def test_provisioned_user_gets_own_credentials(self):
        manager = MagicMock()
        manager.get_credentials_for_user.return_value = ("key-maria", "secret-maria")

        with patch("adapters.canonical_api._get_token_manager", return_value=manager), \
             patch("adapters.canonical_api._user_adapters", {}), \
             patch("adapters.erpnext.client.ERPNextClient") as client_cls, \
             patch("adapters.erpnext.adapter.ERPNextAdapter") as adapter_cls:
            _get_adapter(Caller(email="unique+maria@example.com"))

        assert client_cls.call_args.kwargs["api_key"] == "key-maria"
        adapter_cls.assert_called_once()

    def test_internal_caller_falls_back_to_service_account(self):
        manager = MagicMock()
        manager.get_credentials_for_user.return_value = None
        service = MagicMock()

        with patch("adapters.canonical_api._get_token_manager", return_value=manager), \
             patch("adapters.canonical_api._build_service_adapter", return_value=service):
            got = _get_adapter(Caller(email="svc@example.com", allow_service_account=True))

        assert got is service


class TestLocalHarness:
    """Without an API Gateway event there is no internet exposure, so the local
    uvicorn harness keeps working off the header."""

    def test_no_aws_event_trusts_header(self):
        request = MagicMock()
        request.scope = {}
        caller = _caller(request, x_p2p_user_email="demo+maria@example.com")
        assert caller.email == "demo+maria@example.com"
        assert caller.allow_service_account is True
