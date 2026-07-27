# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
FastAPI application entrypoint for the P2P backend.

Serves operational routes (agent chat, admin, dashboard, config, decisions).
ERP data CRUD is handled by the canonical adapter API at /api/erp/*.
"""

# Fix OpenTelemetry StopIteration in Lambda ZIP packaging.
# entry_points() can't find opentelemetry_context in flat packages.
# Pre-register the context before any otel imports happen.
try:
    from opentelemetry.context.contextvars_context import ContextVarsRuntimeContext
    import opentelemetry.context as _otel_ctx
    _otel_ctx._RUNTIME_CONTEXT = ContextVarsRuntimeContext()
except Exception:
    pass  # nosec B110 -- optional otel pre-init; absence/failure is non-fatal

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.agents import router as agents_router
from api.admin import router as admin_router
from api.dashboard import router as dashboard_router
from api.decisions import router as decisions_router
from api.config_view import router as config_router
from api.invoices import router as invoices_router
from api.chat import router as chat_router
from api.lifecycle import router as lifecycle_router

app = FastAPI(title="Agentic ERP — Procure-to-Pay", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # local dev
        "http://localhost:5174",
        # CloudFront domain added at deploy time via ALLOWED_ORIGINS env var
    ] + [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

# Operational routes (unique to this Lambda — not in canonical adapter API)
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(config_router, prefix="/api/config", tags=["config"])
app.include_router(decisions_router, prefix="/api/decisions", tags=["decisions"])
app.include_router(invoices_router, prefix="/api/invoices", tags=["invoices"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(lifecycle_router, prefix="/api/lifecycle", tags=["lifecycle"])


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Lambda handler via Mangum
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    handler = None
