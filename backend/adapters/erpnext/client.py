# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
ERPNext REST API client.

Handles session/API-key auth, CRUD, and document submission.
Evolved from utilities/scripts/erpnext_client.py for production use.
"""

import json
import logging
import time
from typing import Any, Optional

import requests

logger = logging.getLogger("p2p.adapters.erpnext.client")


class ERPNextClient:
    """Low-level REST client for ERPNext API.

    Supports three auth modes (checked in priority order):
    1. OAuth2 Bearer token (per-user, preferred)
    2. API key + secret (service account)
    3. Username + password session (deprecated)
    """

    def __init__(self, base_url: str,
                 api_key: Optional[str] = None,
                 api_secret: Optional[str] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 oauth_token: Optional[str] = None,
                 host_override: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        # When using an internal ALB (internal.erp.xxx), ERPNext/Frappe needs
        # the original Host header to route to the correct site.
        if host_override:
            self.session.headers["Host"] = host_override

        if oauth_token:
            self.session.headers["Authorization"] = f"Bearer {oauth_token}"
            # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
            logger.info("Authenticated with OAuth2 Bearer token to %s", self.base_url)
        elif api_key and api_secret:
            self.session.headers["Authorization"] = f"token {api_key}:{api_secret}"
            # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
            logger.info("Authenticated with API key to %s", self.base_url)
        elif username and password:
            logger.warning("Username/password auth is deprecated — migrate to OAuth2 or API keys")
            # nosemgrep -- use-timeout: demo/setup script; long-running ERPNext calls are expected
            resp = self.session.post(
                f"{self.base_url}/api/method/login",
                data={"usr": username, "pwd": password},
            )
            resp.raise_for_status()
            logger.info("Session login as %s to %s", username, self.base_url)
        else:
            raise ValueError("Provide oauth_token, api_key+api_secret, or username+password")

    def get_list(
        self,
        doctype: str,
        fields: Optional[list[str]] = None,
        filters: Optional[list] = None,
        or_filters: Optional[list] = None,
        order_by: Optional[str] = None,
        group_by: Optional[str] = None,
        limit: int = 0,
    ) -> list[dict]:
        """List documents of a given doctype."""
        params: dict[str, Any] = {"limit_page_length": limit}
        if fields:
            params["fields"] = json.dumps(fields)
        if filters:
            params["filters"] = json.dumps(filters)
        if or_filters:
            params["or_filters"] = json.dumps(or_filters)
        if order_by:
            params["order_by"] = order_by
        if group_by:
            params["group_by"] = group_by
        resp = self.session.get(
            f"{self.base_url}/api/resource/{doctype}", params=params
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def get(self, doctype: str, name: str) -> dict:
        """Get a single document by name."""
        resp = self.session.get(
            f"{self.base_url}/api/resource/{doctype}/{name}"
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    def insert(self, doctype: str, data: dict, retry: int = 2) -> dict:
        """Insert a new document. Returns created document or empty dict on conflict."""
        data["doctype"] = doctype
        for attempt in range(retry + 1):
            try:
                resp = self.session.post(
                    f"{self.base_url}/api/resource/{doctype}",
                    json={"data": json.dumps(data)},
                )
                if resp.status_code in (409, 417):
                    text = resp.text.lower()
                    if "duplicateentryerror" in text or "already exists" in text:
                        return {}
                    logger.warning(f"Insert {doctype} conflict: {resp.text[:200]}")
                    return {}
                resp.raise_for_status()
                return resp.json().get("data", {})
            except requests.exceptions.ConnectionError:
                if attempt < retry:
                    time.sleep(2)  # nosemgrep: arbitrary-sleep -- transient connect retry backoff
                    continue
                raise

    def submit(self, doctype: str, name: str) -> dict:
        """Submit (finalize) a document."""
        resp = self.session.put(
            f"{self.base_url}/api/resource/{doctype}/{name}",
            json={"data": json.dumps({"docstatus": 1})},
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    def get_count(self, doctype: str, filters: Optional[list] = None) -> int:
        """Get count of documents matching filters."""
        params: dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters)
        resp = self.session.get(
            f"{self.base_url}/api/method/frappe.client.get_count",
            params={"doctype": doctype, **params},
        )
        resp.raise_for_status()
        return int(resp.json().get("message", 0))

    def get_report(self, report_name: str, filters: Optional[dict] = None) -> dict:
        """Run an ERPNext report."""
        params: dict[str, Any] = {"report_name": report_name}
        if filters:
            params["filters"] = json.dumps(filters)
        resp = self.session.get(
            f"{self.base_url}/api/method/frappe.desk.query_report.run",
            params=params,
        )
        resp.raise_for_status()
        return resp.json().get("message", {})
