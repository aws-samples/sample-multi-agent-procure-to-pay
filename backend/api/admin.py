# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Admin endpoints for system status and operational reset.

Provides health checks and a demo reset button that clears operational
DynamoDB tables (decisions, errors, jobs).
"""

import os
import logging

from fastapi import APIRouter, Request

from services import erp_client
from services.auth import get_user_email

router = APIRouter()
logger = logging.getLogger("p2p.admin")


@router.post("/reset")
def reset_data():
    """Clear operational DynamoDB tables (decisions, errors, jobs) for demo reset."""
    import boto3

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"),
    )
    prefix = os.environ.get("DYNAMODB_TABLE_PREFIX", "p2p-dev")
    counts = {}

    for table_suffix, pk in [
        ("document-lifecycle", "document_id"),
        ("invoice-jobs", "job_id"),
    ]:
        try:
            table = dynamodb.Table(f"{prefix}-{table_suffix}")
            scan = table.scan()
            deleted = 0
            with table.batch_writer() as batch:
                for item in scan.get("Items", []):
                    if pk in item:
                        batch.delete_item(Key={pk: item[pk]})
                        deleted += 1
            while scan.get("LastEvaluatedKey"):
                scan = table.scan(ExclusiveStartKey=scan["LastEvaluatedKey"])
                with table.batch_writer() as batch:
                    for item in scan.get("Items", []):
                        if pk in item:
                            batch.delete_item(Key={pk: item[pk]})
                            deleted += 1
            counts[table_suffix] = f"{deleted} deleted"
        except Exception:
            pass  # nosec B110 -- table may not exist yet (admin reset is best-effort)

    return {"status": "reset_complete", "counts": counts}


@router.post("/update-mr-status/{mr_id}")
def update_mr_status(mr_id: str, status: str = "Ordered"):
    """Admin: Force-update a Material Request status in ERPNext."""
    try:
        from adapters.erpnext.client import ERPNextClient
        import json as _json

        # Read ERPNext credentials from Secrets Manager
        import boto3
        secret_arn = os.environ.get("ERPNEXT_SECRET_ARN", "")
        erpnext_url = os.environ.get("ERPNEXT_URL", "")
        if not secret_arn or not erpnext_url:
            return {"mr_id": mr_id, "error": "ERPNEXT_SECRET_ARN or ERPNEXT_URL not set"}

        sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"))
        secret = _json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])

        client = ERPNextClient(
            base_url=erpnext_url,
            api_key=secret.get("service_api_key", ""),
            api_secret=secret.get("service_api_secret", ""),
        )
        # Try PUT update
        resp = client.session.put(
            f"{client.base_url}/api/resource/Material Request/{mr_id}",
            json={"status": status, "per_ordered": 100},
        )
        return {
            "mr_id": mr_id,
            "target_status": status,
            "http_status": resp.status_code,
            "response": resp.text[:500],
        }
    except Exception as e:
        import traceback
        return {"mr_id": mr_id, "error": str(e), "trace": traceback.format_exc()[:500]}


@router.get("/status")
def data_status(request: Request):
    """Quick count of ERP records via canonical adapter API."""
    if not erp_client.is_configured():
        return {"error": "ERP adapter transport not configured"}

    user_email = get_user_email(request)
    counts = {}
    for entity in ["suppliers", "items", "requisitions", "purchase-orders", "receipts", "invoices", "payments"]:
        try:
            resp = erp_client.request("GET", f"/{entity}", user_email=user_email, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            counts[entity] = data.get("total", len(data.get("items", [])))
        except Exception as e:
            logger.warning("Failed to fetch count for %s: %s", entity, e)
            counts[entity] = -1

    return counts
