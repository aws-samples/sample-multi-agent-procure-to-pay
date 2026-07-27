# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""HTTP client for the Canonical P2P API with per-user identity."""

import logging
import time
from typing import Optional

import requests

from .config import CANONICAL_API_URL

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]  # seconds

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
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _request(self, method: str, path: str, user_email: Optional[str] = None, **kwargs) -> dict:
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
