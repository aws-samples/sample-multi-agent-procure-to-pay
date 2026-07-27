# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Seed the local ERPNext with demo data by driving the utilities scripts.

The demo seed/verify scripts under utilities/scripts/ (04_seed_demo_data.py,
05_verify_demo_data.py) are the project's canonical setup runbook and are also
used for real AWS deployments, so they stay where they are — this wrapper just
points them at the local ERPNext. (Script 02_setup_users.py is skipped locally:
it provisions Cognito users, and the harness runs in guest mode without Cognito.)

Prerequisites: local ERPNext is up (infra/docker/docker-compose.local-test.yaml)
and its Frappe setup wizard has been completed once (Company "Apex Manufacturing
Group", warehouse "Stores - AMG") — the seed script depends on those, per the
README. This wrapper is a no-op-friendly convenience, invoked by `make seed` or
when ARIA_SEED_ON_START=true.

Usage:
    python local/scripts/seed_local.py [--url http://localhost:8080]
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s seed-local %(message)s")
logger = logging.getLogger("seed_local")

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "utilities" / "scripts"


def _run(script: str, url: str) -> int:
    path = SCRIPTS / script
    if not path.exists():
        logger.error("missing script %s", path)
        return 1
    env = dict(os.environ)
    env.setdefault("ERPNEXT_URL", url)
    logger.info("running %s against %s", script, url)
    # Use the current interpreter; scripts read ERPNEXT_URL / --url.
    return subprocess.run(  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
        [sys.executable, str(path), "--url", url],
        cwd=str(SCRIPTS),
        env=env,
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed local ERPNext with demo data.")
    parser.add_argument(
        "--url",
        default=os.getenv("ERPNEXT_URL", "http://localhost:8080"),
        help="Local ERPNext base URL",
    )
    args = parser.parse_args()

    rc = _run("04_seed_demo_data.py", args.url)
    if rc != 0:
        logger.error("seeding failed (rc=%d) — is ERPNext up and the setup wizard complete?", rc)
        return rc
    _run("05_verify_demo_data.py", args.url)
    logger.info("local seed complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
