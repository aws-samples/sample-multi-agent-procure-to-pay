#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
End-to-end verification of the role authorization design against a LIVE
deployment of P2PAuthE2EStack.

Uses a throwaway user and checks every link of the chain with real Cognito
tokens and real AgentCore Gateway + Policy Engine decisions:

  1. Sign in as a requester (SRP, the frontend's auth flow).
  2. Tokens: p2p_role == "requester" on BOTH tokens; custom:role on neither.
  3. UpdateUserAttributes custom:role=approver with the user's own access
     token  ->  must be rejected by Cognito (writeAttributes).
     Positive control: given_name IS writable (proves the client works).
  4. Re-authenticate: claims unchanged.
  5. Gateway (Cognito JWT inbound auth, Cedar ENFORCE):
       tools/call erp___create_payment      -> denied
       tools/call erp___create_requisition  -> allowed (requester permit)
       tools/call erp___list_suppliers      -> allowed (read permit)
  6. Even when an OPERATOR sets custom:role=admin on the profile, the token
     still says p2p_role=requester and create_payment is still denied: the
     attribute is dead for authorization.
  7. Legitimate path: operator adds the user to the "approver" group ->
     p2p_role == "approver" and create_payment is now allowed.
  8. Cleanup: the user is deleted (always).

Usage:
    pip install -r tests/e2e/requirements.txt
    npm run e2e:deploy
    python3 tests/e2e/run_e2e.py [--stack P2PAuthE2EStack] [--region us-east-1]
    npm run e2e:destroy

Exit code 0 only if every check passed.
"""

import argparse
import base64
import json
import secrets
import string
import sys
import time
import uuid
from dataclasses import dataclass, field

import boto3
import requests
from botocore.exceptions import ClientError
from pycognito import Cognito

ROLE_CLAIM = "p2p_role"
TOOL_READ = "erp___list_suppliers"
TOOL_REQUESTER_WRITE = "erp___create_requisition"
TOOL_PRIVILEGED_WRITE = "erp___create_payment"


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

@dataclass
class Report:
    results: list = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f"\n         {detail}" if detail else ""))
        return ok

    @property
    def failed(self) -> list:
        return [r for r in self.results if not r[1]]


def step(title: str) -> None:
    print(f"\n== {title}")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def stack_outputs(cfn, stack_name: str) -> dict:
    resp = cfn.describe_stacks(StackName=stack_name)
    return {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}


def decode_claims(token: str) -> dict:
    """Decode the JWT payload. The token came straight from Cognito over TLS in
    this process, so signature verification adds nothing here."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def random_password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(16))
    return f"Aa1{core}"  # satisfies upper/lower/digit, no symbols required


def authenticate(pool_id: str, client_id: str, region: str, username: str, password: str):
    """SRP sign-in, the same flow the frontend uses (authFlows.userSrp)."""
    u = Cognito(pool_id, client_id, user_pool_region=region, username=username)
    u.authenticate(password=password)
    return u.id_token, u.access_token


class McpGateway:
    """Minimal MCP-over-StreamableHTTP client for AgentCore Gateway."""

    def __init__(self, url: str, access_token: str):
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }

    def _rpc(self, method: str, params: dict) -> dict:
        body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
        resp = requests.post(self.url, headers=self.headers, json=body, timeout=60)
        text = resp.text
        if resp.headers.get("content-type", "").startswith("text/event-stream"):
            # Take the last JSON data: line of the SSE stream.
            data_lines = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
            text = data_lines[-1] if data_lines else "{}"
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError:
            payload = {"raw": text}
        payload["_http_status"] = resp.status_code
        return payload

    def list_tools(self) -> list:
        out = self._rpc("tools/list", {})
        return [t["name"] for t in out.get("result", {}).get("tools", [])]

    def call_tool(self, name: str, arguments: dict | None = None) -> tuple:
        """Return (outcome, summary) where outcome is one of:
        "allowed" (tool executed), "denied" (rejected by authorization),
        "error" (anything else: protocol error, unknown tool, 5xx).
        Keeping "denied" distinct from "error" stops a broken harness from
        masquerading as a passing security check."""
        out = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        status = out.get("_http_status", 200)
        err = out.get("error")
        result = out.get("result", {})
        text = json.dumps(err if err else result.get("content") if result else out.get("raw"))
        if status in (401, 403) or (err and _looks_like_denial(text)) or (result.get("isError") and _looks_like_denial(text)):
            return "denied", f"HTTP {status} {text[:300]}"
        if status >= 400 or err or result.get("isError"):
            return "error", f"HTTP {status} {text[:300]}"
        return "allowed", text[:300]


def _looks_like_denial(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("not authorized", "unauthorized", "access denied", "accessdenied", "forbidden", "policy"))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack", default="P2PAuthE2EStack")
    ap.add_argument("--region", default=None)
    args = ap.parse_args()

    session = boto3.Session(region_name=args.region)
    region = session.region_name
    cfn = session.client("cloudformation")
    idp = session.client("cognito-idp")

    outputs = stack_outputs(cfn, args.stack)
    pool_id = outputs["CognitoUserPoolId"]
    client_id = outputs["CognitoClientId"]
    gateway_url = outputs.get("GatewayUrl")
    print(f"Stack {args.stack} in {region}: pool={pool_id} client={client_id}")
    print(f"Gateway: {gateway_url or '(none; gateway checks skipped)'}")

    report = Report()
    username = f"e2e+{secrets.token_hex(4)}@example.invalid"
    password = random_password()

    try:
        # ---------------------------------------------------------------
        step("0. Provision a throwaway requester (operator path)")
        idp.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": username},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "given_name", "Value": "E2E"},
                {"Name": "family_name", "Value": "Requester"},
                {"Name": "custom:role", "Value": "requester"},
                {"Name": "custom:department", "Value": "Manufacturing"},
            ],
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
        )
        idp.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)
        idp.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName="requester")
        print(f"  created {username} in group requester")

        # ---------------------------------------------------------------
        step("1. Sign in (SRP) and inspect tokens")
        id_token, access_token = authenticate(pool_id, client_id, region, username, password)
        idc, acc = decode_claims(id_token), decode_claims(access_token)
        report.check("ID token carries p2p_role=requester", idc.get(ROLE_CLAIM) == "requester", f"p2p_role={idc.get(ROLE_CLAIM)!r}")
        report.check("Access token carries p2p_role=requester", acc.get(ROLE_CLAIM) == "requester", f"p2p_role={acc.get(ROLE_CLAIM)!r}")
        report.check("custom:role suppressed from ID token", "custom:role" not in idc)
        report.check("custom:role absent from access token", "custom:role" not in acc)
        report.check("cognito:groups == [requester]", idc.get("cognito:groups") == ["requester"], str(idc.get("cognito:groups")))

        # ---------------------------------------------------------------
        step("2. Self-update custom:role with the user's own access token")
        for attr, value in (("custom:role", "approver"), ("custom:role", "admin"), ("custom:department", "Finance")):
            try:
                idp.update_user_attributes(AccessToken=access_token, UserAttributes=[{"Name": attr, "Value": value}])
                report.check(f"UpdateUserAttributes {attr}={value} rejected", False, "Cognito ACCEPTED the write")
            except ClientError as e:
                code = e.response["Error"]["Code"]
                msg = e.response["Error"]["Message"]
                report.check(f"UpdateUserAttributes {attr}={value} rejected", code == "NotAuthorizedException", f"{code}: {msg}")

        # Positive control: a display attribute must still be writable, so the
        # rejections above are the writeAttributes allowlist, not a broken client.
        try:
            idp.update_user_attributes(AccessToken=access_token, UserAttributes=[{"Name": "given_name", "Value": "Updated"}])
            report.check("Positive control: given_name writable by user", True)
        except ClientError as e:
            report.check("Positive control: given_name writable by user", False, str(e))

        profile = {a["Name"]: a["Value"] for a in idp.admin_get_user(UserPoolId=pool_id, Username=username)["UserAttributes"]}
        report.check("Profile custom:role still 'requester' after self-update attempt", profile.get("custom:role") == "requester", f"custom:role={profile.get('custom:role')!r}")
        report.check("Profile given_name updated (control)", profile.get("given_name") == "Updated")

        # ---------------------------------------------------------------
        step("3. Re-authenticate: claims unchanged")
        id_token, access_token = authenticate(pool_id, client_id, region, username, password)
        idc, acc = decode_claims(id_token), decode_claims(access_token)
        report.check("p2p_role still requester on both tokens", idc.get(ROLE_CLAIM) == "requester" and acc.get(ROLE_CLAIM) == "requester")

        # ---------------------------------------------------------------
        if gateway_url:
            step("4. Gateway + Cedar (ENFORCE) with the requester's access token")
            gw = McpGateway(gateway_url, access_token)
            tools = gw.list_tools()
            # Policy enforcement also filters tools/list: a requester sees the
            # 15 read tools + create_requisition, and never the privileged writes.
            report.check("tools/list returns the requester's tool set", TOOL_REQUESTER_WRITE in tools and len(tools) == 16, f"{len(tools)} tools")
            report.check(f"{TOOL_PRIVILEGED_WRITE} hidden from requester's tools/list", TOOL_PRIVILEGED_WRITE not in tools)

            outcome, detail = gw.call_tool(TOOL_READ)
            report.check(f"{TOOL_READ} allowed (read permit)", outcome == "allowed", f"{outcome}: {detail}")
            outcome, detail = gw.call_tool(TOOL_REQUESTER_WRITE, {"purpose": "e2e"})
            report.check(f"{TOOL_REQUESTER_WRITE} allowed (requester permit)", outcome == "allowed", f"{outcome}: {detail}")
            outcome, detail = gw.call_tool(TOOL_PRIVILEGED_WRITE, {"supplier_id": "S1", "amount": 1})
            report.check(f"{TOOL_PRIVILEGED_WRITE} DENIED for requester", outcome == "denied", f"{outcome}: {detail}")

            # -----------------------------------------------------------
            step("5. Operator sets custom:role=admin on the profile: must change nothing")
            idp.admin_update_user_attributes(UserPoolId=pool_id, Username=username,
                                             UserAttributes=[{"Name": "custom:role", "Value": "admin"}])
            id_token, access_token = authenticate(pool_id, client_id, region, username, password)
            idc, acc = decode_claims(id_token), decode_claims(access_token)
            report.check("p2p_role still requester with custom:role=admin on profile",
                         idc.get(ROLE_CLAIM) == "requester" and acc.get(ROLE_CLAIM) == "requester")
            report.check("custom:role=admin not present in any token", "custom:role" not in idc and "custom:role" not in acc)
            outcome, detail = McpGateway(gateway_url, access_token).call_tool(TOOL_PRIVILEGED_WRITE, {"supplier_id": "S1", "amount": 1})
            report.check(f"{TOOL_PRIVILEGED_WRITE} still DENIED", outcome == "denied", f"{outcome}: {detail}")

            # -----------------------------------------------------------
            step("6. Legitimate path: operator adds user to 'approver' group")
            idp.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName="approver")
            id_token, access_token = authenticate(pool_id, client_id, region, username, password)
            acc = decode_claims(access_token)
            report.check("p2p_role == approver (most privileged group wins)", acc.get(ROLE_CLAIM) == "approver", f"p2p_role={acc.get(ROLE_CLAIM)!r} groups={acc.get('cognito:groups')}")
            gw = McpGateway(gateway_url, access_token)
            report.check(f"{TOOL_PRIVILEGED_WRITE} now listed for approver", TOOL_PRIVILEGED_WRITE in gw.list_tools())
            outcome, detail = gw.call_tool(TOOL_PRIVILEGED_WRITE, {"supplier_id": "S1", "amount": 1})
            report.check(f"{TOOL_PRIVILEGED_WRITE} ALLOWED for approver", outcome == "allowed", f"{outcome}: {detail}")
        else:
            print("  (no GatewayUrl output; skipping Gateway/Cedar checks)")

    finally:
        step("Cleanup")
        try:
            idp.admin_delete_user(UserPoolId=pool_id, Username=username)
            print(f"  deleted {username}")
        except ClientError as e:
            print(f"  WARNING could not delete {username}: {e}")

    print("\n" + "=" * 70)
    failed = report.failed
    total = len(report.results)
    if failed:
        print(f"E2E RESULT: FAIL ({len(failed)}/{total} checks failed)")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")
        return 1
    print(f"E2E RESULT: PASS ({total}/{total} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
