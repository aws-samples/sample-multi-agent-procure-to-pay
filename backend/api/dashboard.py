# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Dashboard API — aggregated metrics for the P2P pipeline.

Fetches ERP data via the canonical adapter API (separate Lambda in VPC).
"""

import logging

from fastapi import APIRouter, Request

from services import erp_client
from services.auth import get_user_email

router = APIRouter()
logger = logging.getLogger("p2p.dashboard")


@router.get("/metrics")
def get_dashboard_metrics(request: Request):
    """Aggregated pipeline metrics from ERP."""
    if not erp_client.is_configured():
        logger.warning("ERP adapter transport not configured — returning defaults")
        return _defaults()

    try:
        resp = erp_client.request(
            "GET", "/analytics/spend-summary",
            user_email=get_user_email(request), timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        defaults = _defaults()
        return {k: data.get(k, v) for k, v in defaults.items()}
    except Exception as e:
        logger.warning("Failed to fetch ERP metrics: %s", e)
        return _defaults()


def _defaults() -> dict:
    return {
        "total_spend": 0,
        "total_orders": 0,
        "total_invoices": 0,
        "total_suppliers": 0,
        "open_orders": 0,
        "unpaid_invoices": 0,
        "overdue_invoices": 0,
        "currency": "USD",
    }
