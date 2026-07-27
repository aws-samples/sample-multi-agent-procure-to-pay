# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared fixtures for P2P backend tests."""

import os
import sys
import pytest

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Prevent boto3 from failing on a missing AWS profile at import time.
os.environ.pop("AWS_PROFILE", None)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

# Force config for all tests
os.environ["DYNAMODB_TABLE_PREFIX"] = "p2p-test"
os.environ["AWS_REGION_NAME"] = "us-east-1"


@pytest.fixture(autouse=True)
def _mock_aws_env(monkeypatch):
    """Set fake AWS credentials for moto — scoped to each test, not global."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


def _create_dynamo_tables(dynamodb):
    """Create the DynamoDB tables used by the current P2P backend."""
    prefix = os.environ.get("DYNAMODB_TABLE_PREFIX", "p2p-test")

    simple_tables = {
        f"{prefix}-agent-decisions": "decision_id",
        f"{prefix}-agent-errors": "error_id",
        f"{prefix}-agent-jobs": "job_id",
    }
    for table_name, key_name in simple_tables.items():
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": key_name, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key_name, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )


@pytest.fixture
def mock_dynamo():
    """Provide moto DynamoDB context with all P2P tables created."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_dynamo_tables(dynamodb)
        yield dynamodb


@pytest.fixture
def app_client(mock_dynamo):
    """Return a FastAPI TestClient with mocked DynamoDB tables."""
    from fastapi.testclient import TestClient
    from main import app
    yield TestClient(app)
