# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Provision the local emulators to match the deployed AWS resources.

Creates the DynamoDB tables (same names/keys as the CDK stack), the S3 document
bucket, and the ERPNext credentials secret — all in the in-memory emulators
started by the supervisor. Idempotent: re-running is safe (already-exists is
ignored), so ``make up`` can call it on every start.

Table schema mirrors infra/lib/p2p-agentic-stack.ts (prefix ``p2p-dev``):
  <prefix>-chat-sessions       PK user_id
  <prefix>-document-lifecycle  PK document_id
  <prefix>-invoice-jobs        PK job_id
  <prefix>-simulation-state    PK see CDK
  <prefix>-agent-jobs          PK job_id     (referenced by services code)
  <prefix>-agent-errors        PK error_id   (referenced by services code)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "config"))
import harness_env as H  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s init-aws %(message)s")
logger = logging.getLogger("init_aws")

# (logical name, partition-key attribute). Prefix is applied at creation.
_TABLES = [
    ("chat-sessions", "user_id"),
    ("document-lifecycle", "document_id"),
    ("invoice-jobs", "job_id"),
    ("agent-jobs", "job_id"),
    ("agent-errors", "error_id"),
    ("simulation-state", "pk"),
]


def _client(service: str):
    # Endpoint overrides come from the environment (set by the supervisor);
    # placeholder creds are fine for the emulators.
    return boto3.client(
        service,
        region_name=H.REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local"),
        endpoint_url={
            "dynamodb": os.environ.get("AWS_ENDPOINT_URL_DYNAMODB"),
            "s3": os.environ.get("AWS_ENDPOINT_URL_S3"),
            "secretsmanager": os.environ.get("AWS_ENDPOINT_URL_SECRETS_MANAGER"),
        }[service],
    )


def _create_tables() -> None:
    ddb = _client("dynamodb")
    for name, pk in _TABLES:
        table_name = f"{H.TABLE_PREFIX}-{name}"
        try:
            ddb.create_table(
                TableName=table_name,
                KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            logger.info("created table %s (PK %s)", table_name, pk)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("ResourceInUseException",):
                logger.info("table %s already exists", table_name)
            else:
                raise


def _create_bucket() -> None:
    s3 = _client("s3")
    try:
        s3.create_bucket(Bucket=H.S3_BUCKET)
        logger.info("created bucket %s", H.S3_BUCKET)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            logger.info("bucket %s already exists", H.S3_BUCKET)
        else:
            raise


def _create_secret() -> None:
    """Seed the ERPNext credentials secret the backend bootstraps from.

    canonical_api._bootstrap_from_secret() reads ERPNEXT_SECRET_ARN; for local
    we store service creds so the adapter can talk to the local ERPNext. Values
    come from the env (populated from local/.env) with empty defaults.
    """
    sm = _client("secretsmanager")
    payload = {
        "service_api_key": os.environ.get("ERPNEXT_API_KEY", ""),
        "service_api_secret": os.environ.get("ERPNEXT_API_SECRET", ""),
        "admin_username": os.environ.get("ERPNEXT_USER", "Administrator"),
        "admin_password": os.environ.get("ERPNEXT_PASSWORD", ""),
    }
    try:
        sm.create_secret(Name=H.ERPNEXT_SECRET_NAME, SecretString=json.dumps(payload))
        # Logs the secret's NAME, not its contents.
        logger.info("created secret store %s", H.ERPNEXT_SECRET_NAME)  # nosemgrep: python-logger-credential-disclosure
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceExistsException":
            sm.put_secret_value(SecretId=H.ERPNEXT_SECRET_NAME, SecretString=json.dumps(payload))
            # Logs the secret's NAME, not its contents.
            logger.info("updated secret store %s", H.ERPNEXT_SECRET_NAME)  # nosemgrep: python-logger-credential-disclosure
        else:
            raise


def main() -> int:
    _create_tables()
    _create_bucket()
    _create_secret()
    logger.info("local AWS provisioning complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
