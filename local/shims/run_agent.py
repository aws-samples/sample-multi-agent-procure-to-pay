# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Run one P2P agent as a local HTTP server on a chosen port.

All specialized agents share a single entrypoint, backend/agentcore_app.py — a
BedrockAgentCoreApp whose behavior is selected by the AGENT_NAME env var. In the
cloud each runs in its own container ending with app.run() (binds :8080, serves
POST /invocations + GET /ping). Locally we run several at once, so this launcher
sets AGENT_NAME, imports the app object, and calls app.run(port=N) on the agent's
assigned port. Nothing about the agent code changes — same SDK entrypoint the
cloud serves, just a caller-chosen port.

Usage:
    python local/shims/run_agent.py <agent_name> <port>
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s agent %(message)s")
logger = logging.getLogger("run_agent")

_VALID = {
    "requisition",
    "sourcing",
    "po_management",
    "receiving",
    "invoice_matching",
    "payment",
    "workflow",
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_agent.py <agent_name> <port>")
    agent_name, port_s = sys.argv[1], sys.argv[2]
    if agent_name not in _VALID:
        raise SystemExit(f"unknown agent {agent_name!r}; expected one of {sorted(_VALID)}")
    port = int(port_s)

    # Reproduce the container layout: agentcore_app.py runs with backend/ as the
    # working directory / import root (its `from utils...`, `from agents...`
    # imports are backend-relative).
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    if not (backend_dir / "agentcore_app.py").exists():
        raise SystemExit(f"no agentcore_app.py at {backend_dir}")
    sys.path.insert(0, str(backend_dir))
    os.chdir(backend_dir)

    # AGENT_NAME selects which agent this process serves (read at import time).
    os.environ["AGENT_NAME"] = agent_name

    import agentcore_app  # noqa: E402  -- imported after AGENT_NAME + sys.path set

    logger.info("Serving agent %s on http://127.0.0.1:%d (/invocations, /ping)", agent_name, port)
    agentcore_app.app.run(port=port, host="127.0.0.1")


if __name__ == "__main__":
    main()
