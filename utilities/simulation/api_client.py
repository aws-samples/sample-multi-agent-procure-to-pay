# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Client for the Canonical P2P API with per-user identity.

Transport depends on where this runs. Deployed, ADAPTER_FUNCTION_NAME is set and
the client invokes the Adapter Lambda directly: the ERP HTTP route requires an
end-user Cognito JWT, and a scheduled simulation has no user session to present.
Locally, it falls back to plain HTTP against CANONICAL_API_URL.
"""

import json
import logging
import os
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from .config import CANONICAL_API_URL

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]  # seconds

# Must match _INTERNAL_CALL_KEY in backend/adapters/canonical_api.py. API Gateway
# builds requestContext itself, so an internet client cannot forge this marker.
_INTERNAL_CALL_KEY = "p2pInternalServiceCall"

# Base path the adapter's Mangum handler strips from incoming paths.
_BASE_PATH = "/api/erp"

# Persona → ERPNext email mapping (Contract C5)
# Each document type is created under the appropriate persona.
STEP_USER_MAP = {
    "requisition": "demo+maria@example.com",     # Maria creates PRs
    "purchase_order": "demo+jake@example.com",    # Jake creates POs
    "receipt": "demo+jake@example.com",           # Jake receives goods
    "invoice": "demo+priya@example.com",          # Priya processes invoices
    "payment": "demo+priya@example.com",          # Priya processes payments
}


class CanonicalAPIClient:
    """Thin wrapper around the Canonical P2P REST API.

    Supports per-user identity via X-P2P-User-Email header, so
    documents created by the simulation appear under the correct
    ERPNext user (not Administrator).
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or CANONICAL_API_URL).rstrip("/")
        self.function_name = os.environ.get("ADAPTER_FUNCTION_NAME", "")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._lambda = None

    def _request(self, method: str, path: str, user_email: Optional[str] = None, **kwargs) -> dict:
        if self.function_name:
            return self._invoke_lambda(method, path, user_email, **kwargs)
        return self._invoke_http(method, path, user_email, **kwargs)

    def _invoke_lambda(self, method: str, path: str, user_email: Optional[str], **kwargs) -> dict:
        if self._lambda is None:
            import boto3
            self._lambda = boto3.client(
                "lambda", region_name=os.environ.get("AWS_REGION_NAME", "us-east-1")
            )

        headers = {"accept": "application/json", "host": "erp-adapter.internal"}
        body = kwargs.get("json")
        if body is not None:
            headers["content-type"] = "application/json"
        if user_email:
            headers["x-p2p-user-email"] = user_email

        event = {
            "version": "2.0",
            "rawPath": f"{_BASE_PATH}{path}",
            "rawQueryString": urlencode(kwargs.get("params") or {}, doseq=True),
            "headers": headers,
            "requestContext": {
                _INTERNAL_CALL_KEY: True,
                "http": {
                    "method": method.upper(),
                    "path": f"{_BASE_PATH}{path}",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",
                },
            },
            "body": json.dumps(body) if body is not None else None,
            "isBase64Encoded": False,
        }

        last_error = None
        for attempt in range(MAX_RETRIES):
            result = self._lambda.invoke(
                FunctionName=self.function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(event).encode(),
            )
            payload_raw = result["Payload"].read().decode()

            if result.get("FunctionError"):
                last_error = RuntimeError(f"Adapter Lambda error: {payload_raw}")
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    logger.warning("Adapter error on %s %s, retry in %ds", method, path, wait)
                    time.sleep(wait)
                    continue
                raise last_error

            payload = json.loads(payload_raw or "{}")
            status = int(payload.get("statusCode", 502))
            resp_body = payload.get("body") or ""
            if status >= 400:
                logger.error("HTTP error on %s %s: %s — %s", method, path, status, resp_body)
                raise RuntimeError(f"ERP API returned {status}: {resp_body}")
            return json.loads(resp_body) if resp_body else {}

        raise last_error  # type: ignore[misc]

    def _invoke_http(self, method: str, path: str, user_email: Optional[str], **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        headers = {}
        if user_email:
            headers["X-P2P-User-Email"] = user_email

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=30, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.ConnectionError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    logger.warning("Connection error on %s %s, retry in %ds: %s", method, path, wait, e)
                    time.sleep(wait)
            except requests.exceptions.HTTPError as e:
                logger.error("HTTP error on %s %s: %s — %s", method, path, e, resp.text)
                raise
        raise last_error  # type: ignore[misc]

    # ----- Reads (no user context needed) -----

    def get_requisition(self, requisition_id: str) -> dict:
        return self._request("GET", f"/requisitions/{requisition_id}")

    def get_purchase_order(self, order_id: str) -> dict:
        return self._request("GET", f"/purchase-orders/{order_id}")

    def get_receipt(self, receipt_id: str) -> dict:
        return self._request("GET", f"/receipts/{receipt_id}")

    def get_invoice(self, invoice_id: str) -> dict:
        return self._request("GET", f"/invoices/{invoice_id}")

    def list_suppliers(self) -> dict:
        return self._request("GET", "/suppliers")

    def list_items(self) -> dict:
        return self._request("GET", "/items")

    # ----- Creates (with per-user identity) -----

    def create_requisition(self, data: dict, requester_email: str | None = None) -> dict:
        email = requester_email or STEP_USER_MAP["requisition"]
        return self._request("POST", "/requisitions", user_email=email, json=data)

    def create_purchase_order(self, data: dict) -> dict:
        return self._request("POST", "/purchase-orders", user_email=STEP_USER_MAP["purchase_order"], json=data)

    def create_receipt(self, data: dict) -> dict:
        return self._request("POST", "/receipts", user_email=STEP_USER_MAP["receipt"], json=data)

    def create_invoice(self, data: dict) -> dict:
        return self._request("POST", "/invoices", user_email=STEP_USER_MAP["invoice"], json=data)

    def create_payment(self, data: dict) -> dict:
        return self._request("POST", "/payments", user_email=STEP_USER_MAP["payment"], json=data)

    # ----- Health -----

    def health(self) -> dict:
        return self._request("GET", "/health")
