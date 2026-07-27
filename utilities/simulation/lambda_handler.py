# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Lambda entrypoint for the Simulation Engine.

Two EventBridge rules invoke this handler with different modes:

1. DEMAND mode (every 6 hours):
   EventBridge sends {"mode": "demand"}
   → Creates 1-3 Material Requests from random requesters

2. SCAN mode (every 5 minutes):
   EventBridge sends {"mode": "scan"}
   → Scans for POs needing Purchase Receipts or Invoices
   → Creates documents only after configurable shipping/billing delays

Manual invocation (no mode): runs both demand + scan for testing.
"""

import json
import logging

logger = logging.getLogger("p2p.simulation.lambda")
logger.setLevel(logging.INFO)


def handler(event, context):
    """EventBridge scheduled Lambda handler.

    Routes to the correct simulation mode based on the event payload.
    """
    logger.info("Simulation invoked (event: %s)", json.dumps(event)[:300])

    # Determine mode from event payload
    mode = "both"  # default: run both (for manual testing)
    force_pr_count = None

    if isinstance(event, dict):
        mode = event.get("mode", "both")
        force_pr_count = event.get("force_pr_count")

    try:
        if mode == "demand":
            from simulation.simulator import tick_demand
            summary = tick_demand(force_pr_count=force_pr_count)

        elif mode == "scan_receipts":
            from simulation.simulator import tick_scan_receipts
            summary = tick_scan_receipts()

        elif mode == "scan_invoices":
            from simulation.simulator import tick_scan_invoices
            summary = tick_scan_invoices()

        elif mode == "scan":
            from simulation.simulator import tick_scan
            summary = tick_scan()

        else:
            # "both" — combined mode for manual testing
            from simulation.simulator import tick
            summary = tick(force_pr_count=force_pr_count)

    except Exception as e:
        logger.error("Simulation failed (mode=%s): %s", mode, e, exc_info=True)
        summary = {
            "mode": mode,
            "error": str(e),
            "material_requests_created": 0,
            "receipts_created": 0,
            "invoices_generated": 0,
            "errors": 1,
        }

    logger.info("Simulation complete (mode=%s): %s", mode, json.dumps(summary))

    return {
        "statusCode": 200,
        "body": json.dumps(summary),
    }
