# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""DynamoDB-backed state manager for simulation scenarios."""

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from time import time

import boto3

from .config import AWS_REGION, SCENARIO_TTL_SECONDS, SIMULATION_TABLE

_dynamodb = None


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb.Table(SIMULATION_TABLE)


def _sanitize(obj):
    """Convert floats to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    return obj


def _deserialize(item: dict) -> dict:
    """Convert Decimals back to floats for JSON."""
    return json.loads(json.dumps(item, default=str))


def create_scenario(scenario_type: str, initial_data: dict) -> str:
    """Create a new scenario in PENDING state. Returns scenario_id."""
    scenario_id = str(uuid.uuid4())
    now = datetime.now(tz=None).isoformat()
    _table().put_item(Item=_sanitize({
        "scenario_id": scenario_id,
        "scenario_type": scenario_type,
        "state": "PENDING",
        "created_at": now,
        "updated_at": now,
        "next_action_at": now,  # Ready immediately
        "documents": {},
        "agent_results": {},
        "initial_data": initial_data,
        "error": None,
        "ttl": int(time()) + SCENARIO_TTL_SECONDS,
    }))
    return scenario_id


def get_active_scenarios() -> list[dict]:
    """Return all scenarios that are not COMPLETE or FAILED."""
    resp = _table().scan(
        FilterExpression="NOT #s IN (:c, :f)",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":c": "COMPLETE", ":f": "FAILED"},
    )
    return [_deserialize(item) for item in resp.get("Items", [])]


def get_ready_scenarios() -> list[dict]:
    """Return active scenarios whose next_action_at has passed."""
    now = datetime.now(tz=None).isoformat()
    resp = _table().scan(
        FilterExpression="NOT #s IN (:c, :f) AND next_action_at <= :now",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={
            ":c": "COMPLETE",
            ":f": "FAILED",
            ":now": now,
        },
    )
    return [_deserialize(item) for item in resp.get("Items", [])]


def advance_scenario(
    scenario_id: str,
    new_state: str,
    delay_seconds: int = 0,
    document_updates: dict | None = None,
    agent_result: dict | None = None,
) -> dict:
    """Advance a scenario to a new state with optional delay."""
    now = datetime.now(tz=None)
    next_action = (now + timedelta(seconds=delay_seconds)).isoformat()

    update_expr = "SET #s = :s, updated_at = :u, next_action_at = :n"
    attr_names = {"#s": "state"}
    attr_values: dict = _sanitize({
        ":s": new_state,
        ":u": now.isoformat(),
        ":n": next_action,
    })

    if document_updates:
        for key, val in document_updates.items():
            safe_key = key.replace("-", "_")
            update_expr += f", documents.{safe_key} = :{safe_key}"
            attr_values[f":{safe_key}"] = val

    if agent_result:
        update_expr += ", agent_results.#latest = :ar"
        attr_names["#latest"] = new_state
        attr_values[":ar"] = _sanitize(agent_result)

    resp = _table().update_item(
        Key={"scenario_id": scenario_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
        ReturnValues="ALL_NEW",
    )
    return _deserialize(resp.get("Attributes", {}))


def fail_scenario(scenario_id: str, error: str) -> dict:
    """Mark a scenario as FAILED."""
    now = datetime.now(tz=None).isoformat()
    resp = _table().update_item(
        Key={"scenario_id": scenario_id},
        UpdateExpression="SET #s = :s, updated_at = :u, #e = :e",
        ExpressionAttributeNames={"#s": "state", "#e": "error"},
        ExpressionAttributeValues={
            ":s": "FAILED",
            ":u": now,
            ":e": error,
        },
        ReturnValues="ALL_NEW",
    )
    return _deserialize(resp.get("Attributes", {}))


def get_scenario(scenario_id: str) -> dict | None:
    """Get a single scenario by ID."""
    resp = _table().get_item(Key={"scenario_id": scenario_id})
    item = resp.get("Item")
    return _deserialize(item) if item else None


def get_stats() -> dict:
    """Get counts by scenario type and state."""
    resp = _table().scan(ProjectionExpression="scenario_type, #s",
                         ExpressionAttributeNames={"#s": "state"})
    by_type: dict[str, int] = {}
    by_state: dict[str, int] = {}
    for item in resp.get("Items", []):
        st = item.get("scenario_type", "unknown")
        state = item.get("state", "unknown")
        by_type[st] = by_type.get(st, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
    return {"by_type": by_type, "by_state": by_state, "total": len(resp.get("Items", []))}
