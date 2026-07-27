# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
ERPNext OAuth2 token manager.

Manages per-user credentials for ERPNext access. For tonight's demo,
uses pre-configured API keys per user from environment variables.
Future: exchange AgentCore workload tokens for ERPNext OAuth2 tokens.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("p2p.adapters.erpnext.oauth")

# Contract C5: Cognito User → ERPNext User mapping
USER_EMAIL_MAP = {
    "maria.chen": "demo+maria@example.com",
    "sarah.johnson": "demo+sarah@example.com",
    "jake.rodriguez": "demo+jake@example.com",
    "priya.patel": "demo+priya@example.com",
    "gary.wilson": "demo+gary@example.com",
}


@dataclass
class TokenEntry:
    api_key: str
    api_secret: str
    expires_at: float  # epoch seconds


class ERPNextTokenManager:
    """Manages per-user API credentials for ERPNext.

    Demo mode: reads pre-generated API key pairs from environment variables.
    Env var pattern: ERPNEXT_USER_<SLUG>_KEY / ERPNEXT_USER_<SLUG>_SECRET
    where SLUG is the email with @, + and . replaced by _ (e.g., DEMO_MARIA_EXAMPLE_COM).

    Falls back to a service account for agent operations.
    """

    def __init__(
        self,
        erpnext_url: str,
        service_api_key: Optional[str] = None,
        service_api_secret: Optional[str] = None,
    ):
        self.erpnext_url = erpnext_url
        self._service_api_key = service_api_key or ""
        self._service_api_secret = service_api_secret or ""
        self._cache: dict[str, TokenEntry] = {}
        self._cache_ttl = 3600  # 1 hour

    @staticmethod
    def _email_to_env_slug(email: str) -> str:
        """Convert email to env var slug: demo+maria@example.com → DEMO_MARIA_EXAMPLE_COM"""
        return email.replace("+", "_").replace("@", "_").replace(".", "_").upper()

    def get_credentials_for_user(self, email: str) -> Optional[tuple[str, str]]:
        """Get (api_key, api_secret) for a user. Returns None if not configured."""
        now = time.time()

        # Check cache
        if email in self._cache:
            entry = self._cache[email]
            if entry.expires_at > now:
                return (entry.api_key, entry.api_secret)
            del self._cache[email]

        # Look up from environment
        slug = self._email_to_env_slug(email)
        api_key = os.environ.get(f"ERPNEXT_USER_{slug}_KEY", "")
        api_secret = os.environ.get(f"ERPNEXT_USER_{slug}_SECRET", "")

        if api_key and api_secret:
            self._cache[email] = TokenEntry(
                api_key=api_key,
                api_secret=api_secret,
                expires_at=now + self._cache_ttl,
            )
            # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
            logger.info("Loaded API credentials for user: %s", email)
            return (api_key, api_secret)

        # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
        logger.debug("No credentials configured for user: %s", email)
        return None

    def get_service_credentials(self) -> tuple[str, str]:
        """Get the service account API key pair (for agent operations)."""
        return (self._service_api_key, self._service_api_secret)

    def resolve_email(self, cognito_username: str) -> Optional[str]:
        """Map a Cognito username to an ERPNext user email."""
        return USER_EMAIL_MAP.get(cognito_username)
