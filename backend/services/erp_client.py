# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Internal client for the canonical ERP API (backend/adapters/canonical_api.py).

The ERP data plane is not exposed to the internet without authentication. The
API Lambda reaches it over ``lambda:InvokeFunction`` instead of an HTTP hop
through API Gateway, which keeps the ERP route behind the Cognito JWT authorizer
for browser traffic only.

Requests are shaped as API Gateway v2 proxy events so the adapter's existing
FastAPI routing and Mangum handler serve them unchanged. Each event carries the
``p2pInternalServiceCall`` marker inside ``requestContext``; API Gateway builds
``requestContext`` itself and puts caller-supplied headers in ``headers``, so an
internet client cannot forge that marker.

Set ADAPTER_FUNCTION_NAME to use direct invocation. ADAPTER_API_URL remains
supported for the local dev harness, where the adapter runs as a plain uvicorn
process with no Lambda to invoke.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional
from urllib.parse import urlencode

logger = logging.getLogger("p2p.services.erp_client")

# Must match _INTERNAL_CALL_KEY in backend/adapters/canonical_api.py
_INTERNAL_CALL_KEY = "p2pInternalServiceCall"

# The adapter's Mangum handler is mounted at this base path and strips it.
_BASE_PATH = "/api/erp"

_lambda_client = None


class ERPResponse:
    """Minimal `requests.Response`-alike so call sites read the same either way."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.text = body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return json.loads(self.text) if self.text else None

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"ERP API returned {self.status_code}: {self.text}")


def is_configured() -> bool:
    """True when an ERP transport is available."""
    return bool(os.environ.get("ADAPTER_FUNCTION_NAME") or os.environ.get("ADAPTER_API_URL"))


def _build_event(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[Any] = None,
    user_email: Optional[str] = None,
) -> dict:
    """Shape an API Gateway v2 proxy event for the adapter Lambda."""
    query = urlencode(
        {k: v for k, v in (params or {}).items() if v is not None}, doseq=True
    )

    headers = {"accept": "application/json", "host": "erp-adapter.internal"}
    if json_body is not None:
        headers["content-type"] = "application/json"
    if user_email:
        headers["x-p2p-user-email"] = user_email

    return {
        "version": "2.0",
        "rawPath": f"{_BASE_PATH}{path}",
        "rawQueryString": query,
        "headers": headers,
        "requestContext": {
            # Unforgeable from the internet: API Gateway owns requestContext.
            _INTERNAL_CALL_KEY: True,
            "http": {
                "method": method.upper(),
                "path": f"{_BASE_PATH}{path}",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
            },
        },
        "body": json.dumps(json_body) if json_body is not None else None,
        "isBase64Encoded": False,
    }


def request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[Any] = None,
    user_email: Optional[str] = None,
    timeout: int = 30,
) -> ERPResponse:
    """Call the canonical ERP API. `path` is relative to the ERP base path."""
    function_name = os.environ.get("ADAPTER_FUNCTION_NAME")

    if function_name:
        return _invoke_lambda(function_name, method, path, params, json_body, user_email)

    adapter_url = os.environ.get("ADAPTER_API_URL")
    if not adapter_url:
        raise RuntimeError(
            "No ERP transport configured: set ADAPTER_FUNCTION_NAME (deployed) "
            "or ADAPTER_API_URL (local dev)"
        )
    return _invoke_http(adapter_url, method, path, params, json_body, user_email, timeout)


def _invoke_lambda(
    function_name: str,
    method: str,
    path: str,
    params: Optional[dict],
    json_body: Optional[Any],
    user_email: Optional[str],
) -> ERPResponse:
    global _lambda_client

    if _lambda_client is None:
        import boto3
        _lambda_client = boto3.client(
            "lambda", region_name=os.environ.get("AWS_REGION_NAME", "us-east-1")
        )

    event = _build_event(method, path, params, json_body, user_email)
    result = _lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode(),
    )

    if result.get("FunctionError"):
        payload = result["Payload"].read().decode()
        logger.error("Adapter Lambda error on %s %s: %s", method, path, payload)
        return ERPResponse(502, payload)

    payload = json.loads(result["Payload"].read().decode() or "{}")
    body = payload.get("body") or ""
    if payload.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode()
    return ERPResponse(int(payload.get("statusCode", 502)), body)


def _invoke_http(
    adapter_url: str,
    method: str,
    path: str,
    params: Optional[dict],
    json_body: Optional[Any],
    user_email: Optional[str],
    timeout: int,
) -> ERPResponse:
    import requests

    headers = {"x-p2p-user-email": user_email} if user_email else {}
    resp = requests.request(
        method.upper(),
        f"{adapter_url.rstrip('/')}{path}",
        params=params,
        json=json_body,
        headers=headers,
        timeout=timeout,
    )
    return ERPResponse(resp.status_code, resp.text)
