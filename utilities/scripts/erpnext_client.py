# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
ERPNext REST API client for data loading.
Handles authentication, CRUD operations, and document submission.
"""

import requests
import json
import time
from typing import Any
from config import (
    ERPNEXT_URL,
    ERPNEXT_API_KEY,
    ERPNEXT_API_SECRET,
    ERPNEXT_USER,
    ERPNEXT_PASSWORD,
)


class ERPNextClient:
    def __init__(self):
        self.base_url = ERPNEXT_URL.rstrip("/")
        self.session = requests.Session()
        self._authenticate()

    def _authenticate(self):
        """Authenticate via API key or session login."""
        if ERPNEXT_API_KEY and ERPNEXT_API_SECRET:
            self.session.headers.update(
                {"Authorization": f"token {ERPNEXT_API_KEY}:{ERPNEXT_API_SECRET}"}
            )
            print(f"Authenticated with API key to {self.base_url}")
        else:
            resp = self.session.post(
                f"{self.base_url}/api/method/login",
                data={"usr": ERPNEXT_USER, "pwd": ERPNEXT_PASSWORD},
            )
            resp.raise_for_status()
            print(f"Session login successful as {ERPNEXT_USER} to {self.base_url}")

    def get_list(
        self,
        doctype: str,
        filters: dict | None = None,
        fields: list[str] | None = None,
        limit: int = 0,
    ) -> list[dict]:
        """List documents of a given doctype."""
        params: dict[str, Any] = {"limit_page_length": limit}
        if filters:
            params["filters"] = json.dumps(filters)
        if fields:
            params["fields"] = json.dumps(fields)
        resp = self.session.get(
            f"{self.base_url}/api/resource/{doctype}", params=params
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def get(self, doctype: str, name: str) -> dict:
        """Get a single document."""
        resp = self.session.get(f"{self.base_url}/api/resource/{doctype}/{name}")
        resp.raise_for_status()
        return resp.json().get("data", {})

    def insert(self, doctype: str, data: dict, retry: int = 2) -> dict:
        """Insert a new document."""
        data["doctype"] = doctype
        for attempt in range(retry + 1):
            try:
                resp = self.session.post(
                    f"{self.base_url}/api/resource/{doctype}",
                    json={"data": json.dumps(data)},
                )
                if resp.status_code in (409, 417):
                    label = data.get('name', data.get('supplier_name', data.get('item_code', data.get('address_title', '?'))))
                    err = resp.json().get("exc_type", resp.json().get("exception", "")[:80])
                    if "DuplicateEntryError" in str(err) or "already exists" in resp.text.lower():
                        print(f"  [SKIP] {doctype} already exists: {label}")
                        return {}
                    print(f"  [WARN] {doctype} {label}: {err}")
                    return {}
                resp.raise_for_status()
                return resp.json().get("data", {})
            except requests.exceptions.ConnectionError:
                if attempt < retry:
                    time.sleep(2)  # nosemgrep: arbitrary-sleep -- transient connect retry backoff
                    continue
                raise

    def submit(self, doctype: str, name: str) -> dict:
        """Submit (finalize) a document via amend_and_submit workflow."""
        resp = self.session.put(
            f"{self.base_url}/api/resource/{doctype}/{name}",
            json={"data": json.dumps({"docstatus": 1})},
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    def call_method(self, method: str, **kwargs) -> Any:
        """Call a whitelisted server method."""
        resp = self.session.post(
            f"{self.base_url}/api/method/{method}", json=kwargs
        )
        resp.raise_for_status()
        return resp.json().get("message")

    def exists(self, doctype: str, name: str) -> bool:
        """Check if a document exists."""
        try:
            self.get(doctype, name)
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return False
            raise

    def delete(self, doctype: str, name: str):
        """Delete a document."""
        resp = self.session.delete(f"{self.base_url}/api/resource/{doctype}/{name}")
        resp.raise_for_status()
