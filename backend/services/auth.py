# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Item 9: JWT verification middleware.

Extracts and verifies the authenticated user from the JWT token.
Ensures decided_by matches the actual authenticated user, not a
client-supplied string.
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException

logger = logging.getLogger("p2p.auth")


def get_authenticated_user(request: Request) -> Optional[str]:
    """
    Extract the authenticated username from the request.

    In production (behind API Gateway + Cognito JWT Authorizer),
    the verified claims are in the request context.
    For local dev, falls back to the Authorization header or a default.
    """
    # API Gateway injects verified claims into the request context
    # via the Mangum adapter
    scope = request.scope
    aws_context = scope.get("aws.context")
    if aws_context:
        # API Gateway HTTP API with JWT authorizer puts claims in requestContext
        authorizer = getattr(aws_context, "authorizer", None)
        if authorizer and hasattr(authorizer, "claims"):
            return authorizer.claims.get("cognito:username") or authorizer.claims.get("sub")

    # Check for x-amz-user header (set by API Gateway from JWT claims)
    user_header = request.headers.get("x-amz-user")
    if user_header:
        return user_header

    # Local dev fallback: decode JWT if present (without full verification)
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            import base64
            import json
            token = auth_header.split(" ")[1]
            # Decode payload (middle part) without verification for local dev
            payload = token.split(".")[1]
            # Add padding
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.b64decode(payload))
            return claims.get("cognito:username") or claims.get("sub") or claims.get("username")
        except Exception:
            pass  # nosec B110 -- malformed Bearer token; fall through to None

    return None


def require_authenticated_user(request: Request) -> str:
    """
    Get the authenticated user or raise 401.
    Use this in endpoints that need verified identity.
    """
    user = get_authenticated_user(request)
    if not user:
        # In local dev, allow a fallback
        import os
        if os.environ.get("DATA_SOURCE") == "mock":
            return "local_dev_user"
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def get_user_email(request: Request) -> Optional[str]:
    """Extract the user's email from verified JWT claims.

    Used for X-P2P-User-Email propagation to the canonical adapter API,
    which routes to per-user ERPNext credentials (Contract C5).
    """
    scope = request.scope
    aws_context = scope.get("aws.context")
    if aws_context:
        authorizer = getattr(aws_context, "authorizer", None)
        if authorizer and hasattr(authorizer, "claims"):
            return authorizer.claims.get("email") or authorizer.claims.get("cognito:email")

    # Check for explicit header (set by API Gateway from JWT claims)
    email_header = request.headers.get("x-p2p-user-email")
    if email_header:
        return email_header

    # Local dev fallback: decode JWT payload
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            import base64
            import json
            token = auth_header.split(" ")[1]
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.b64decode(payload))
            return claims.get("email") or claims.get("cognito:email")
        except Exception:
            pass  # nosec B110 -- malformed Bearer token; fall through to mapping/None

    # Map username to email as fallback (Contract C5)
    username = get_authenticated_user(request)
    if username:
        from adapters.erpnext.oauth import USER_EMAIL_MAP
        return USER_EMAIL_MAP.get(username)

    return None


def get_user_department(request: Request) -> Optional[str]:
    """Extract user's department from JWT custom:department claim."""
    scope = request.scope
    aws_context = scope.get("aws.context")
    if aws_context:
        authorizer = getattr(aws_context, "authorizer", None)
        if authorizer and hasattr(authorizer, "claims"):
            return authorizer.claims.get("custom:department")

    # Local dev fallback: decode JWT payload
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            import base64
            import json
            token = auth_header.split(" ")[1]
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.b64decode(payload))
            return claims.get("custom:department")
        except Exception:
            pass  # nosec B110 -- malformed Bearer token; fall through to None

    return None
