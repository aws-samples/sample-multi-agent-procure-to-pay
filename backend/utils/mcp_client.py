# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Shared MCP client builder for AgentCore Gateway.

Used by both agentcore_app.py (AgentCore Runtimes) and chat_agent.py (Lambda).
The Gateway uses IAM auth (SigV4), so we create a custom httpx client that
signs every request with the caller's execution role credentials.
"""

import logging
import os

logger = logging.getLogger("p2p.mcp_client")


def build_mcp_client(gateway_url: str | None = None):
    """Build an MCP client connected to the AgentCore Gateway.

    Args:
        gateway_url: Gateway endpoint URL. Defaults to GATEWAY_ENDPOINT env var.

    Returns:
        MCPClient instance, or None if gateway_url is not set or connection fails.
    """
    url = gateway_url or os.environ.get("GATEWAY_ENDPOINT", "")
    if not url:
        logger.warning("GATEWAY_ENDPOINT not set — MCP tools unavailable")
        return None

    try:
        import httpx
        from botocore.session import Session as BotocoreSession
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from strands.tools.mcp import MCPClient
        from mcp.client.streamable_http import streamable_http_client

        region = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "us-east-1"))
        botocore_session = BotocoreSession()
        credentials = botocore_session.get_credentials().get_frozen_credentials()

        class _SigV4Auth(httpx.Auth):
            """httpx Auth that signs requests with SigV4 for bedrock-agentcore."""
            def auth_flow(self, request):
                aws_req = AWSRequest(
                    method=request.method,
                    url=str(request.url),
                    headers=dict(request.headers),
                    data=request.content if request.content else b"",
                )
                SigV4Auth(credentials, "bedrock-agentcore", region).add_auth(aws_req)
                for key, val in aws_req.headers.items():
                    request.headers[key] = val
                yield request

        # Timeout is set via the httpx.Timeout object below (bandit B113 can't
        # see it through the object, so annotate).
        client = httpx.AsyncClient(auth=_SigV4Auth(), timeout=httpx.Timeout(30.0))  # nosec B113
        return MCPClient(
            lambda: streamable_http_client(url=url, http_client=client),
        )
    except Exception as e:
        logger.error(f"Failed to create MCP client: {e}")
        return None
