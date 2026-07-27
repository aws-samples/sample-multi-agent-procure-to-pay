# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
DynamoDB helper functions for table access, CRUD, and scans.

Wraps boto3 with the configured table prefix from application settings.
"""

import boto3
from typing import Optional
from config import settings

dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)


def get_table(name: str):
    return dynamodb.Table(f"{settings.dynamodb_table_prefix}-{name}")


def put_item(table_name: str, item: dict) -> dict:
    table = get_table(table_name)
    table.put_item(Item=item)
    return item


def get_item(table_name: str, key: dict) -> Optional[dict]:
    table = get_table(table_name)
    resp = table.get_item(Key=key, ConsistentRead=True)
    return resp.get("Item")


def update_item(table_name: str, key: dict, updates: dict) -> dict:
    expr_parts = []
    expr_values = {}
    expr_names = {}
    for i, (k, v) in enumerate(updates.items()):
        expr_parts.append(f"#{k} = :val{i}")
        expr_values[f":val{i}"] = v
        expr_names[f"#{k}"] = k

    table = get_table(table_name)
    resp = table.update_item(
        Key=key,
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeValues=expr_values,
        ExpressionAttributeNames=expr_names,
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def scan_table(table_name: str, filter_expr=None, expr_values=None) -> list[dict]:
    table = get_table(table_name)
    kwargs = {}
    if filter_expr:
        kwargs["FilterExpression"] = filter_expr
    if expr_values:
        kwargs["ExpressionAttributeValues"] = expr_values
    resp = table.scan(**kwargs)
    return resp.get("Items", [])
