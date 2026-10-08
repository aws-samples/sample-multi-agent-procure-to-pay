# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Role authorization tests: a user-writable Cognito attribute must never grant
a privileged action set.

Models the full token chain with synthetic identities and no AWS calls:

  1. A user self-updates their Cognito attributes (UpdateUserAttributes) and
     sets custom:role to a privileged value.
  2. Cognito issues a token. The Pre Token Generation trigger
     (lambda/pre_token_generation/handler.py) runs on the user's attributes
     and Group membership.
  3. AgentCore Gateway maps the token's claims to tags on the OAuthUser
     principal and evaluates policies/p2p-procurement.cedar.

The Cedar evaluation uses the real policy file via cedarpy (Rust Cedar
bindings). Install with: pip install -r tests/requirements.txt
"""

import copy
import importlib.util
import json
import os
import sys

import pytest

cedarpy = pytest.importorskip("cedarpy", reason="pip install -r infra/tests/requirements.txt")

HERE = os.path.dirname(__file__)
POLICY_FILE = os.path.join(HERE, "..", "policies", "p2p-procurement.cedar")
HANDLER_FILE = os.path.join(HERE, "..", "lambda", "pre_token_generation", "handler.py")

GATEWAY_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test-gw"

WRITE_TOOLS = {
    "erp___create_requisition": {"requester", "procurement", "admin"},
    "erp___create_purchase_order": {"procurement", "admin"},
    "erp___create_receipt": {"procurement", "admin"},
    "erp___create_invoice": {"ap_clerk", "procurement", "admin"},
    "erp___create_payment": {"ap_clerk", "approver", "admin"},
}
ALL_ROLES = ["requester", "approver", "ap_clerk", "procurement", "executive", "admin"]


def _load_handler():
    spec = importlib.util.spec_from_file_location("pre_token_generation_handler", HANDLER_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pre_token():
    return _load_handler()


@pytest.fixture(scope="module")
def policies():
    """The policy set exactly as the CDK stack deploys it: comments stripped,
    `resource is AgentCore::Gateway` scoped to the concrete gateway ARN."""
    with open(POLICY_FILE, encoding="utf-8") as f:
        raw = f.read()
    stripped = "\n".join(
        line for line in raw.split("\n") if not line.strip().startswith("//")
    )
    return stripped.replace(
        "resource is AgentCore::Gateway",
        f'resource == AgentCore::Gateway::"{GATEWAY_ARN}"',
    )


# --------------------------------------------------------------------------
# Synthetic Cognito -> AgentCore pipeline
# --------------------------------------------------------------------------

def cognito_event(user_attributes: dict, groups: list, version: str = "2") -> dict:
    """Pre Token Generation event for a user with the given attributes and
    group memberships. Version 2 (the one the CDK stack registers) by default."""
    return {
        "version": version,
        "triggerSource": "TokenGeneration_Authentication",
        "userPoolId": "us-east-1_TEST",
        "userName": user_attributes.get("email", "user@example.com"),
        "request": {
            "userAttributes": dict(user_attributes),
            "groupConfiguration": {
                "groupsToOverride": list(groups),
                "iamRolesToOverride": [],
                "preferredRole": None,
            },
            "scopes": ["openid", "email", "profile"],
        },
        "response": {},
    }


def _apply_override(base_claims: dict, override: dict) -> dict:
    claims = dict(base_claims)
    claims.update(override.get("claimsToAddOrOverride", {}))
    for name in override.get("claimsToSuppress", []):
        claims.pop(name, None)
    return claims


def issue_tokens(pre_token, user_attributes: dict, groups: list) -> tuple:
    """Simulate Cognito V2 token issuance and return (id_claims, access_claims).

    ID token starts from the user's attributes (how Cognito populates custom:*
    claims); the access token never carries custom attributes. Both carry
    cognito:groups. The trigger's per-token override details are then applied.
    """
    event = pre_token.handler(cognito_event(user_attributes, groups))
    details = event["response"]["claimsAndScopeOverrideDetails"]

    common = {"sub": user_attributes["sub"], "iss": "https://cognito-idp.test"}
    if groups:
        common["cognito:groups"] = list(groups)
    id_base = {**common, **{k: v for k, v in user_attributes.items() if k.startswith("custom:")}}
    access_base = {**common, "client_id": "frontend", "scope": "openid email profile"}

    return (
        _apply_override(id_base, details["idTokenGeneration"]),
        _apply_override(access_base, details["accessTokenGeneration"]),
    )


def issue_id_token(pre_token, user_attributes: dict, groups: list) -> dict:
    return issue_tokens(pre_token, user_attributes, groups)[0]


def oauth_principal_entity(claims: dict) -> dict:
    """How the Gateway builds the OAuthUser entity: JWT claims become tags.
    Cedar tags are string-valued, so list claims are JSON-encoded."""
    tags = {}
    for k, v in claims.items():
        if k == "sub":
            continue
        tags[k] = v if isinstance(v, str) else json.dumps(v)
    return {
        "uid": {"type": "AgentCore::OAuthUser", "id": claims["sub"]},
        "attrs": {"id": claims["sub"]},
        "parents": [],
        "tags": tags,
    }


def is_allowed(policies: str, claims: dict, tool: str) -> bool:
    request = {
        "principal": f'AgentCore::OAuthUser::"{claims["sub"]}"',
        "action": f'AgentCore::Action::"{tool}"',
        "resource": f'AgentCore::Gateway::"{GATEWAY_ARN}"',
        "context": {"input": {}},
    }
    result = cedarpy.is_authorized(request, policies, [oauth_principal_entity(claims)])
    assert not result.diagnostics.errors, result.diagnostics.errors
    return result.decision == cedarpy.Decision.Allow


REQUESTER = {
    "sub": "11111111-1111-1111-1111-111111111111",
    "email": "maria.chen@example.com",
    "custom:role": "requester",
    "custom:department": "Manufacturing",
}


# --------------------------------------------------------------------------
# User-writable attributes must not affect authorization
# --------------------------------------------------------------------------

class TestUserAttributesDoNotGrantRoles:
    @pytest.mark.parametrize("claimed_role", ["approver", "procurement", "ap_clerk", "admin"])
    def test_self_updated_custom_role_grants_nothing(self, pre_token, policies, claimed_role):
        """A requester sets custom:role to a privileged value via
        UpdateUserAttributes. Their action set must be unchanged."""
        before = issue_id_token(pre_token, REQUESTER, groups=["requester"])

        tampered = copy.deepcopy(REQUESTER)
        tampered["custom:role"] = claimed_role
        after = issue_id_token(pre_token, tampered, groups=["requester"])

        for tool, permitted_roles in WRITE_TOOLS.items():
            expected = "requester" in permitted_roles
            assert is_allowed(policies, before, tool) is expected, tool
            assert is_allowed(policies, after, tool) is expected, (
                f"custom:role={claimed_role} changed the decision for {tool}"
            )

    def test_the_original_repro_is_denied(self, pre_token, policies):
        """requester -> custom:role=approver -> create_payment, using either
        token. Must be Deny."""
        tampered = {**REQUESTER, "custom:role": "approver"}
        id_claims, access_claims = issue_tokens(pre_token, tampered, groups=["requester"])
        assert is_allowed(policies, id_claims, "erp___create_payment") is False
        assert is_allowed(policies, access_claims, "erp___create_payment") is False

    def test_custom_role_never_reaches_either_token(self, pre_token):
        id_claims, access_claims = issue_tokens(
            pre_token, {**REQUESTER, "custom:role": "admin"}, ["requester"]
        )
        for claims in (id_claims, access_claims):
            assert "custom:role" not in claims
            assert claims["p2p_role"] == "requester"

    def test_v1_event_still_handled(self, pre_token):
        """Pools still on the V1 trigger (ID token only) get the same claim."""
        event = pre_token.handler(cognito_event(REQUESTER, ["approver"], version="1"))
        override = event["response"]["claimsOverrideDetails"]
        assert override["claimsToAddOrOverride"] == {"p2p_role": "approver"}
        assert "custom:role" in override["claimsToSuppress"]
        assert "claimsAndScopeOverrideDetails" not in event["response"]

    def test_forged_p2p_role_attribute_is_ignored(self, pre_token, policies):
        """Even if a user could somehow write an attribute literally named
        p2p_role, the trigger overrides the claim from group membership."""
        forged = {**REQUESTER, "custom:p2p_role": "admin", "p2p_role": "admin"}
        claims = issue_id_token(pre_token, forged, groups=["requester"])
        assert claims["p2p_role"] == "requester"
        assert is_allowed(policies, claims, "erp___create_payment") is False

    def test_user_with_no_group_has_no_write_access(self, pre_token, policies):
        claims = issue_id_token(pre_token, {**REQUESTER, "custom:role": "admin"}, groups=[])
        assert "p2p_role" not in claims
        for tool in WRITE_TOOLS:
            assert is_allowed(policies, claims, tool) is False, tool
        # Read access for any authenticated OAuth user is unchanged.
        assert is_allowed(policies, claims, "erp___list_suppliers") is True


# --------------------------------------------------------------------------
# The legitimate path still works: group membership drives the action set
# --------------------------------------------------------------------------

class TestGroupMembershipDrivesAuthorization:
    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_action_set_matches_group(self, pre_token, policies, role):
        user = {**REQUESTER, "custom:role": "requester"}  # attribute is irrelevant
        claims = issue_id_token(pre_token, user, groups=[role])
        assert claims["p2p_role"] == role
        for tool, permitted_roles in WRITE_TOOLS.items():
            assert is_allowed(policies, claims, tool) is (role in permitted_roles), (tool, role)

    def test_multiple_groups_pick_most_privileged(self, pre_token):
        assert pre_token.resolve_role(["requester", "approver"]) == "approver"
        assert pre_token.resolve_role(["executive", "admin", "requester"]) == "admin"

    def test_unknown_group_yields_no_role(self, pre_token):
        assert pre_token.resolve_role(["marketing"]) is None
        assert pre_token.resolve_role([]) is None
        assert pre_token.resolve_role(None) is None

    def test_precedence_matches_cdk_group_list(self, pre_token):
        auth = os.path.join(HERE, "..", "lib", "p2p-auth.ts")
        with open(auth, encoding="utf-8") as f:
            src = f.read()
        import re
        m = re.search(r"P2P_ROLE_GROUPS = \[([^\]]+)\]", src)
        assert m, "P2P_ROLE_GROUPS not found in p2p-auth.ts"
        cdk_groups = re.findall(r'"([a-z_]+)"', m.group(1))
        assert cdk_groups == pre_token.ROLE_PRECEDENCE


# --------------------------------------------------------------------------
# Infrastructure guard: the app clients must not expose custom:* for writing
# (lib/p2p-auth.ts is used by both P2PAgenticStack and P2PAuthE2EStack)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def stack_src():
    """Source of the Cognito construct shared by the production and E2E stacks."""
    with open(os.path.join(HERE, "..", "lib", "p2p-auth.ts"), encoding="utf-8") as f:
        return f.read()


class TestAppClientWriteAttributes:
    @pytest.mark.parametrize("client_id", ["FrontendClient", "ERPNextSSOClient"])
    def test_client_sets_explicit_write_attributes(self, stack_src, client_id):
        start = stack_src.index(f'addClient("{client_id}"')
        block = stack_src[start : stack_src.index("});", start)]
        assert "writeAttributes: userWritableAttributes" in block, (
            f"{client_id} relies on Cognito's default (all attributes writable)"
        )

    def test_writable_set_excludes_custom_attributes(self, stack_src):
        start = stack_src.index("const userWritableAttributes")
        block = stack_src[start : stack_src.index(";", start)]
        assert "withCustomAttributes" not in block
        assert "custom:" not in block

    def test_pre_token_trigger_is_wired_as_v2(self, stack_src):
        assert "UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG" in stack_src
        assert "LambdaVersion.V2_0" in stack_src
        assert "FeaturePlan.ESSENTIALS" in stack_src, "V2 trigger needs Essentials"
