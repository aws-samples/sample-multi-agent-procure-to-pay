# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Cognito Pre Token Generation trigger — asserts the P2P role server-side.

Why this exists
---------------
The Cedar policies on the AgentCore Gateway decide which ERP write tools a
user may call based on a claim in the user's JWT. Cognito user attributes such
as ``custom:role`` are writable by the user themselves through
``UpdateUserAttributes`` unless the app client restricts them, so a user
attribute is not a safe authorization input.

This trigger makes the role an operator-controlled fact: it is derived from
Cognito Group membership (changed only via ``AdminAddUserToGroup``) and
emitted as the ``p2p_role`` claim. The user-writable ``custom:role`` claim is
suppressed from the token so nothing downstream can key on it by accident.

Cedar policies (infra/policies/p2p-procurement.cedar) and the frontend read
``p2p_role``. Nothing reads ``custom:role`` for authorization.

Event shape: Pre Token Generation V2_0 (ID + access token) with V1_0 fallback
(https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html)
The CDK stack registers this function as a V2_0 trigger so `p2p_role` is
stamped on BOTH tokens. A gateway configured for Cognito JWT inbound auth may
validate either token, so both must carry the server-asserted role. V2
requires the Cognito Essentials plan, which the stack sets explicitly.
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Name of the claim Cedar and the frontend evaluate.
ROLE_CLAIM = "p2p_role"

# Claims removed from the issued tokens. custom:role is user-writable history;
# it must never reach a policy engine as a tag.
SUPPRESSED_CLAIMS = ["custom:role"]

# Group -> role. A user should be in exactly one group; if an operator puts a
# user in several, the most privileged wins (listed first). Keep in sync with
# the `groups` list in infra/lib/p2p-agentic-stack.ts.
ROLE_PRECEDENCE = [
    "admin",
    "procurement",
    "approver",
    "ap_clerk",
    "executive",
    "requester",
]


def resolve_role(groups: Optional[list]) -> Optional[str]:
    """Pick the single P2P role for a set of Cognito group names.

    Returns None when the user is in no recognised group; such a user gets no
    role claim and therefore matches none of the Cedar write permits.
    """
    if not groups:
        return None
    members = {g for g in groups if isinstance(g, str)}
    for role in ROLE_PRECEDENCE:
        if role in members:
            if len(members) > 1:
                logger.warning(
                    "user is in multiple P2P groups %s; asserting %s",
                    sorted(members),
                    role,
                )
            return role
    logger.warning("user groups %s match no known P2P role", sorted(members))
    return None


def handler(event: dict, _context: Any = None) -> dict:
    request = event.get("request") or {}
    group_config = request.get("groupConfiguration") or {}
    groups = group_config.get("groupsToOverride") or []

    role = resolve_role(groups)

    claims_to_add = {ROLE_CLAIM: role} if role else {}
    token_override = {
        "claimsToAddOrOverride": claims_to_add,
        "claimsToSuppress": list(SUPPRESSED_CLAIMS),
    }

    event.setdefault("response", {})
    if str(event.get("version", "1")).startswith("1"):
        # V1_0: ID token only.
        event["response"]["claimsOverrideDetails"] = token_override
    else:
        # V2_0 / V3_0: ID and access tokens in one response. Copy the dict so a
        # consumer mutating one token's override cannot affect the other.
        event["response"]["claimsAndScopeOverrideDetails"] = {
            "idTokenGeneration": dict(token_override),
            "accessTokenGeneration": dict(token_override),
        }

    logger.info(
        json.dumps(
            {
                "trigger": event.get("triggerSource"),
                "user_pool": event.get("userPoolId"),
                "groups": groups,
                ROLE_CLAIM: role,
            }
        )
    )
    return event
