#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Generate MCP Gateway tools schema from the FastAPI canonical API.

Extracts the OpenAPI spec from the FastAPI app and converts it to the
AgentCore Gateway ToolSchema format (array of {name, description, inputSchema}).

Called by CDK during synth via execSync. Output goes to stdout as JSON.
"""

import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

# Suppress logging during import
import logging
logging.disable(logging.CRITICAL)

# Set minimal env vars so config doesn't fail
os.environ.setdefault("DATA_SOURCE", "erpnext")
os.environ.setdefault("ERPNEXT_URL", "https://localhost")
os.environ.setdefault("ERPNEXT_API_KEY", "dummy")
os.environ.setdefault("ERPNEXT_API_SECRET", "dummy")
os.environ.setdefault("AWS_REGION_NAME", "us-east-1")

from adapters.canonical_api import app

spec = app.openapi()


# ── Helpers: sanitize schema types for AgentCore ─────────────────────────────
# AgentCore's schema parser does NOT support:
#   - null types (from Python Optional[X] → anyOf [{type:X}, {type:null}])
#   - default values on properties
# These helpers resolve $ref pointers and coerce unsupported types to safe ones.

VALID_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


def _resolve_schema(schema: dict, openapi_spec: dict) -> dict:
    """Resolve a $ref or anyOf to a concrete schema dict."""
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        return openapi_spec.get("components", {}).get("schemas", {}).get(ref_name, schema)
    # Handle anyOf (e.g. Optional[str] → anyOf: [{type:string}, {type:null}])
    if "anyOf" in schema:
        for variant in schema["anyOf"]:
            resolved = _resolve_schema(variant, openapi_spec)
            t = resolved.get("type")
            if t and t != "null" and t in VALID_TYPES:
                # Merge description/title from parent if present
                merged = {**resolved}
                if "description" in schema:
                    merged.setdefault("description", schema["description"])
                if "title" in schema:
                    merged.setdefault("title", schema["title"])
                return merged
        # Fallback: return first non-null variant or original
        return schema
    return schema


def _safe_type(schema: dict) -> str:
    """Return a type string guaranteed to be in AgentCore's allowed set."""
    t = schema.get("type")
    if t in VALID_TYPES:
        return t
    # null, None, or missing → default to string
    return "string"


tools = []
for path, methods in spec.get("paths", {}).items():
    for method, details in methods.items():
        operation_id = details.get("operationId")
        if not operation_id:
            continue

        # Skip non-tool endpoints (health, internal, auto-generated)
        if "health" in operation_id.lower():
            continue

        summary = details.get("summary", "")
        description = details.get("description", summary)

        # Build input schema from parameters and request body
        properties = {}
        required = []

        # Path parameters
        for param in details.get("parameters", []):
            if param.get("in") == "path":
                name = param["name"]
                schema = param.get("schema", {"type": "string"})
                properties[name] = {
                    "type": schema.get("type", "string"),
                    "description": param.get("description", name),
                }
                if param.get("required", True):
                    required.append(name)

            # Query parameters
            elif param.get("in") == "query":
                name = param["name"]
                schema = _resolve_schema(param.get("schema", {"type": "string"}), spec)
                properties[name] = {
                    "type": _safe_type(schema),
                    "description": param.get("description", name),
                }

        # Request body (JSON)
        request_body = details.get("requestBody", {})
        if request_body:
            content = request_body.get("content", {})
            json_content = content.get("application/json", {})
            body_schema = json_content.get("schema", {})

            # Resolve $ref
            ref = body_schema.get("$ref", "")
            if ref:
                schema_name = ref.split("/")[-1]
                body_schema = spec.get("components", {}).get("schemas", {}).get(schema_name, {})

            if body_schema.get("properties"):
                for prop_name, prop_schema in body_schema["properties"].items():
                    # Skip internal/header fields
                    if prop_name.startswith("x_") or prop_name == "x_p2p_user_email":
                        continue
                    resolved = _resolve_schema(prop_schema, spec)
                    prop_type = _safe_type(resolved)
                    prop_entry = {
                        "type": prop_type,
                        "description": resolved.get("description", resolved.get("title", prop_name)),
                    }
                    # Handle arrays
                    if prop_type == "array" and "items" in resolved:
                        items_resolved = _resolve_schema(resolved["items"], spec)
                        if items_resolved.get("type") == "object" and "properties" in items_resolved:
                            prop_entry["items"] = {
                                "type": "object",
                                "properties": {
                                    k: {"type": _safe_type(v), "description": v.get("description", v.get("title", k))}
                                    for k, v in items_resolved["properties"].items()
                                },
                            }
                        else:
                            prop_entry["items"] = {"type": _safe_type(items_resolved)}
                    properties[prop_name] = prop_entry

                for req_field in body_schema.get("required", []):
                    if req_field not in required and req_field != "x_p2p_user_email":
                        required.append(req_field)

        # Skip file upload endpoints (not suitable for MCP tools)
        if any("multipart" in str(content) for content in request_body.get("content", {}).keys()):
            continue

        input_schema = {"type": "object"}
        if properties:
            input_schema["properties"] = properties
        if required:
            input_schema["required"] = required

        tools.append({
            "name": operation_id,
            "description": description[:500],  # Gateway has length limits
            "inputSchema": input_schema,
        })

print(json.dumps(tools, indent=2))
