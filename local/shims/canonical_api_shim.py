# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Serve the canonical P2P API as a standalone REST server (local only).

In the cloud the canonical API (backend/adapters/canonical_api.py) is deployed as
a Lambda behind API Gateway at the base path ``/api/erp`` (see the Mangum handler
in that module). The SPA's ERP data calls (frontend/src/erpApi.ts) hit
``/api/erp/*``. The MCP gateway shim already imports this FastAPI app to expose it
as agent tools, but the SPA needs it over plain HTTP too — so this shim mounts the
same app under ``/api/erp`` and serves it with uvicorn.

Same app object as production; only the serving mechanism is local. ERP calls hit
the local ERPNext via ERPNEXT_URL; DynamoDB/S3/Secrets resolve to the emulators
via the endpoint env the supervisor sets.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s canonical-api-shim %(message)s"
)
logger = logging.getLogger("canonical_api_shim")


def _build():
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    sys.path.insert(0, str(backend_dir))

    from fastapi import FastAPI
    from adapters import canonical_api

    # Mount the canonical app under /api/erp to match the deployed API Gateway
    # base path (frontend/src/erpApi.ts calls /api/erp/*).
    root = FastAPI(title="P2P Canonical API (local)")
    root.mount("/api/erp", canonical_api.app)
    return root


app = _build()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("ARIA_CANONICAL_API_PORT", "8001"))
    logger.info("canonical API shim serving /api/erp on http://127.0.0.1:%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
