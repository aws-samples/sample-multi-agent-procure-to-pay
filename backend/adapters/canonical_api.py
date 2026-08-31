# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Canonical P2P REST API.

FastAPI app exposing ERP-agnostic procurement endpoints.
Deployed as a Lambda behind AgentCore Gateway (OpenAPI target).
Gateway auto-generates MCP tools from this API's OpenAPI spec.
"""

import os
import json
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import (
    Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile,
)
from mangum import Mangum

from adapters.models import (
    Supplier, SupplierList,
    Item, ItemList,
    Requisition, RequisitionCreate, RequisitionList,
    PurchaseOrder, PurchaseOrderCreate, PurchaseOrderList,
    Receipt, ReceiptCreate, ReceiptList,
    Invoice, InvoiceCreate, InvoiceList,
    Payment, PaymentCreate, PaymentList,
    SpendSummary, SupplierPerformanceList, BudgetStatusList,
    InvoiceExtractionRequest, InvoiceExtractionResult,
)
from adapters.erp_adapter_base import ERPAdapterBase

logger = logging.getLogger("p2p.canonical_api")


def _bootstrap_from_secret():
    """Load ERPNext credentials from Secrets Manager into environment variables.

    The CDK stack stores credentials in a Secrets Manager secret and passes
    the ARN via ERPNEXT_SECRET_ARN. This function reads the secret at cold
    start and populates the env vars that the adapter code expects.
    """
    secret_arn = os.environ.get("ERPNEXT_SECRET_ARN", "")
    if not secret_arn:
        return
    # Skip if already bootstrapped
    if os.environ.get("_ERPNEXT_BOOTSTRAP_DONE"):
        return
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"))
        resp = client.get_secret_value(SecretId=secret_arn)
        creds = json.loads(resp["SecretString"])
        if creds.get("service_api_key"):
            os.environ.setdefault("ERPNEXT_API_KEY", creds["service_api_key"])
        if creds.get("service_api_secret"):
            os.environ.setdefault("ERPNEXT_API_SECRET", creds["service_api_secret"])
        if creds.get("admin_username"):
            os.environ.setdefault("ERPNEXT_USER", creds["admin_username"])
        if creds.get("admin_password"):
            os.environ.setdefault("ERPNEXT_PASSWORD", creds["admin_password"])
        # Per-user keys — unpack nested user_keys dict into env vars
        # Secret format: {"user_keys": {"demo+maria@example.com": {"api_key": "...", "api_secret": "..."}}}
        # Token manager expects: ERPNEXT_USER_DEMO_MARIA_EXAMPLE_COM_KEY / _SECRET
        user_keys = creds.get("user_keys", {})
        if isinstance(user_keys, dict):
            for email, keys in user_keys.items():
                if isinstance(keys, dict) and keys.get("api_key") and keys.get("api_secret"):
                    slug = email.replace("+", "_").replace("@", "_").replace(".", "_").upper()
                    os.environ.setdefault(f"ERPNEXT_USER_{slug}_KEY", keys["api_key"])
                    os.environ.setdefault(f"ERPNEXT_USER_{slug}_SECRET", keys["api_secret"])
                    # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
                    logger.debug("Loaded user credentials for %s", email)
        os.environ["_ERPNEXT_BOOTSTRAP_DONE"] = "1"
        logger.info("Bootstrapped ERPNext credentials from Secrets Manager")
    except Exception as e:
        # Log only the exception type, not the message/args, which could echo
        # secret material pulled from Secrets Manager.
        # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
        logger.warning("Failed to load ERPNext secret: %s", type(e).__name__)


_bootstrap_from_secret()

app = FastAPI(
    title="P2P Canonical API",
    version="1.0.0",
    description=(
        "ERP-agnostic Procure-to-Pay API. Provides canonical data access for "
        "procurement operations — suppliers, items, requisitions, purchase orders, "
        "receipts, invoices, and payments. Backend adapters translate these operations "
        "to specific ERP systems (ERPNext, SAP, Workday, Infor)."
    ),
)


_service_adapter: Optional[ERPAdapterBase] = None
_token_manager = None  # singleton ERPNextTokenManager
_user_adapters: dict[str, ERPAdapterBase] = {}
_MAX_USER_ADAPTERS = 20


def _get_token_manager():
    """Lazy-init singleton token manager."""
    global _token_manager
    if _token_manager is None:
        from adapters.erpnext.oauth import ERPNextTokenManager
        _token_manager = ERPNextTokenManager(
            erpnext_url=os.environ.get("ERPNEXT_URL", ""),
            service_api_key=os.environ.get("ERPNEXT_API_KEY", ""),
            service_api_secret=os.environ.get("ERPNEXT_API_SECRET", ""),
        )
    return _token_manager


# Sentinel placed in requestContext by services/erp_client.py when it invokes
# this Lambda directly. API Gateway builds requestContext itself and copies
# client headers into `headers` only, so an internet client cannot set this.
_INTERNAL_CALL_KEY = "p2pInternalServiceCall"


@dataclass(frozen=True)
class Caller:
    """Resolved identity for one request, and what it is allowed to use.

    `email` is only ever taken from verified JWT claims for requests that
    arrived through API Gateway. `allow_service_account` is true only for
    trusted non-internet callers (direct Lambda invoke, AgentCore Gateway,
    and the local dev harness), which have no end-user token to present.
    """

    email: Optional[str] = None
    allow_service_account: bool = False


def _caller(
    request: Request,
    x_p2p_user_email: Optional[str] = Header(None),
) -> Caller:
    """Resolve the acting identity for an incoming HTTP request.

    Behind API Gateway the identity comes from the JWT claims the authorizer
    verified; the x-p2p-user-email header is ignored, since any client can set
    it. Trusted internal callers may name a user via that header because they
    reach this Lambda without traversing API Gateway.
    """
    event = request.scope.get("aws.event")

    if not isinstance(event, dict):
        # No API Gateway event: the local dev harness (uvicorn), the MCP gateway
        # shim, or a test importing `app` directly. None of these are reachable
        # from the internet in a deployed stack.
        return Caller(email=x_p2p_user_email, allow_service_account=True)

    request_context = event.get("requestContext") or {}

    if request_context.get(_INTERNAL_CALL_KEY):
        return Caller(email=x_p2p_user_email, allow_service_account=True)

    claims = ((request_context.get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    email = claims.get("email") or claims.get("cognito:email")
    if not email:
        raise HTTPException(
            status_code=401,
            detail="Unauthenticated: request carries no verified user identity",
        )
    return Caller(email=email, allow_service_account=False)


def _build_service_adapter() -> ERPAdapterBase:
    """Build (once) the shared full-access service-account adapter."""
    global _service_adapter

    if _service_adapter is None:
        from adapters.erpnext.client import ERPNextClient
        from adapters.erpnext.adapter import ERPNextAdapter

        _service_adapter = ERPNextAdapter(ERPNextClient(
            base_url=os.environ.get("ERPNEXT_URL", ""),
            api_key=os.environ.get("ERPNEXT_API_KEY", ""),
            api_secret=os.environ.get("ERPNEXT_API_SECRET", ""),
            username=os.environ.get("ERPNEXT_USER", ""),
            password=os.environ.get("ERPNEXT_PASSWORD", ""),
        ))

    return _service_adapter


def _get_adapter(caller: Optional[Caller] = None) -> ERPAdapterBase:
    """Get the ERP adapter that `caller` is entitled to use.

    Resolves to the caller's own ERPNext credentials whenever possible. The
    shared service account is only reachable by callers that carry
    `allow_service_account`; for everyone else a missing or unprovisioned
    identity is an error rather than a silent escalation.
    """
    erp_type = os.environ.get("ERP_TYPE", "erpnext")
    if erp_type != "erpnext":
        raise ValueError(f"Unknown ERP_TYPE: {erp_type}")

    caller = caller or Caller()

    if caller.email:
        if caller.email in _user_adapters:
            return _user_adapters[caller.email]

        creds = _get_token_manager().get_credentials_for_user(caller.email)
        if creds:
            from adapters.erpnext.client import ERPNextClient
            from adapters.erpnext.adapter import ERPNextAdapter

            api_key, api_secret = creds
            adapter = ERPNextAdapter(ERPNextClient(
                base_url=os.environ.get("ERPNEXT_URL", ""),
                api_key=api_key, api_secret=api_secret,
            ))
            # Bounded cache — evict oldest entry when full
            if len(_user_adapters) >= _MAX_USER_ADAPTERS:
                _user_adapters.pop(next(iter(_user_adapters)))
            _user_adapters[caller.email] = adapter
            logger.info("Created per-user adapter for %s", caller.email)
            return adapter

        if not caller.allow_service_account:
            # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
            logger.warning("No ERPNext credentials provisioned for %s", caller.email)
            raise HTTPException(
                status_code=403,
                detail="No ERPNext credentials are provisioned for this user",
            )
        # nosemgrep -- python-logger-credential-disclosure: logs status words / exception type / resource name, not secret values
        logger.debug("No credentials for %s, falling back to service account", caller.email)

    elif not caller.allow_service_account:
        raise HTTPException(
            status_code=401,
            detail="Unauthenticated: request carries no verified user identity",
        )

    return _build_service_adapter()


# --- Health ---

@app.get("/health")
def health():
    return {"status": "ok", "erp_type": os.environ.get("ERP_TYPE", "erpnext")}


# --- Suppliers ---

@app.get("/suppliers", response_model=SupplierList,
         summary="List all suppliers",
         operation_id="list_suppliers")
def list_suppliers(
    status: Optional[str] = Query(None, description="Filter by status: active, blocked, inactive"),
    group: Optional[str] = Query(None, description="Filter by supplier group"),
    caller: Caller = Depends(_caller),
):
    """List all suppliers in the ERP system. Optionally filter by status or group."""
    return _get_adapter(caller).list_suppliers(status=status, group=group)


@app.get("/suppliers/{supplier_id}", response_model=Supplier,
         summary="Get supplier details",
         operation_id="get_supplier")
def get_supplier(supplier_id: str, caller: Caller = Depends(_caller)):
    """Get detailed information for a specific supplier by ID."""
    try:
        return _get_adapter(caller).get_supplier(supplier_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Supplier not found: {supplier_id}")


# --- Items ---

@app.get("/items", response_model=ItemList,
         summary="List all items/materials",
         operation_id="list_items")
def list_items(
    group: Optional[str] = Query(None, description="Filter by item group"),
    search: Optional[str] = Query(None, description="Search by item name"),
    caller: Caller = Depends(_caller),
):
    """List all items/materials in the catalog. Optionally filter by group or search term."""
    return _get_adapter(caller).list_items(group=group, search=search)


@app.get("/items/{item_id}", response_model=Item,
         summary="Get item details",
         operation_id="get_item")
def get_item(item_id: str, caller: Caller = Depends(_caller)):
    """Get detailed information for a specific item/material by ID."""
    try:
        return _get_adapter(caller).get_item(item_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")


# --- Requisitions ---

@app.get("/requisitions", response_model=RequisitionList,
         summary="List purchase requisitions",
         operation_id="list_requisitions")
def list_requisitions(
    status: Optional[str] = Query(None, description="Filter by status"),
    requester: Optional[str] = Query(None, description="Filter by requester"),
    detail: bool = Query(True, description="Enrich with line items (slower). Set false for summaries."),
    caller: Caller = Depends(_caller),
):
    """List purchase requisitions (material requests). Filter by status or requester."""
    return _get_adapter(caller).list_requisitions(status=status, requester=requester, detail=detail)


@app.get("/requisitions/{requisition_id}", response_model=Requisition,
         summary="Get requisition details with line items",
         operation_id="get_requisition")
def get_requisition(requisition_id: str, caller: Caller = Depends(_caller)):
    """Get a purchase requisition with all line items by ID."""
    try:
        return _get_adapter(caller).get_requisition(requisition_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Requisition not found: {requisition_id}")


@app.post("/requisitions", response_model=Requisition, status_code=201,
          summary="Create a new purchase requisition",
          operation_id="create_requisition")
def create_requisition(data: RequisitionCreate, caller: Caller = Depends(_caller)):
    """Create and submit a new purchase requisition (material request)."""
    # Auto-assign line numbers if not provided
    for i, item in enumerate(data.line_items):
        if item.line_number == 0:
            item.line_number = i + 1
    return _get_adapter(caller).create_requisition(data)


@app.post("/requisitions/{requisition_id}/status",
          summary="Update requisition status",
          operation_id="update_requisition_status")
def update_requisition_status(requisition_id: str, status: str = "Ordered",
                               caller: Caller = Depends(_caller)):
    """Update a requisition's status in ERPNext (e.g., mark as Ordered after PO creation)."""
    adapter = _get_adapter(caller)
    try:
        adapter._update_mr_ordered_status(requisition_id)
        return {"requisition_id": requisition_id, "status": status, "updated": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update status: {e}")


@app.post("/requisitions/{requisition_id}/stop",
          summary="Stop a requisition",
          operation_id="stop_requisition")
def stop_requisition(requisition_id: str,
                     caller: Caller = Depends(_caller)):
    """Stop a Material Request in ERPNext (used when a human rejects it)."""
    adapter = _get_adapter(caller)
    try:
        adapter.stop_requisition(requisition_id)
        return {"requisition_id": requisition_id, "status": "stopped", "updated": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop requisition: {e}")


# --- Purchase Orders ---

@app.get("/purchase-orders", response_model=PurchaseOrderList,
         summary="List purchase orders",
         operation_id="list_purchase_orders")
def list_purchase_orders(
    supplier_id: Optional[str] = Query(None, description="Filter by supplier"),
    status: Optional[str] = Query(None, description="Filter by status"),
    caller: Caller = Depends(_caller),
):
    """List purchase orders. Filter by supplier or status."""
    return _get_adapter(caller).list_purchase_orders(supplier_id=supplier_id, status=status)


@app.get("/purchase-orders/{order_id}", response_model=PurchaseOrder,
         summary="Get purchase order details with line items",
         operation_id="get_purchase_order")
def get_purchase_order(order_id: str, caller: Caller = Depends(_caller)):
    """Get a purchase order with all line items by ID."""
    try:
        return _get_adapter(caller).get_purchase_order(order_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Purchase order not found: {order_id}")


@app.post("/purchase-orders", response_model=PurchaseOrder, status_code=201,
          summary="Create a new purchase order",
          operation_id="create_purchase_order")
def create_purchase_order(data: PurchaseOrderCreate, caller: Caller = Depends(_caller)):
    """Create and submit a new purchase order."""
    return _get_adapter(caller).create_purchase_order(data)


# --- Receipts ---

@app.get("/receipts", response_model=ReceiptList,
         summary="List goods receipts",
         operation_id="list_receipts")
def list_receipts(
    order_id: Optional[str] = Query(None, description="Filter by purchase order ID"),
    caller: Caller = Depends(_caller),
):
    """List goods receipts (purchase receipts). Filter by related purchase order."""
    return _get_adapter(caller).list_receipts(order_id=order_id)


@app.get("/receipts/{receipt_id}", response_model=Receipt,
         summary="Get receipt details with line items",
         operation_id="get_receipt")
def get_receipt(receipt_id: str, caller: Caller = Depends(_caller)):
    """Get a goods receipt with all line items by ID."""
    try:
        return _get_adapter(caller).get_receipt(receipt_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Receipt not found: {receipt_id}")


@app.post("/receipts", response_model=Receipt, status_code=201,
          summary="Create a new goods receipt",
          operation_id="create_receipt")
def create_receipt(data: ReceiptCreate, caller: Caller = Depends(_caller)):
    """Create and submit a new goods receipt (purchase receipt)."""
    return _get_adapter(caller).create_receipt(data)


# --- Invoices ---

@app.get("/invoices", response_model=InvoiceList,
         summary="List purchase invoices",
         operation_id="list_invoices")
def list_invoices(
    supplier_id: Optional[str] = Query(None, description="Filter by supplier"),
    status: Optional[str] = Query(None, description="Filter by status"),
    caller: Caller = Depends(_caller),
):
    """List purchase invoices. Filter by supplier or status."""
    return _get_adapter(caller).list_invoices(supplier_id=supplier_id, status=status)


@app.get("/invoices/{invoice_id}", response_model=Invoice,
         summary="Get invoice details with line items",
         operation_id="get_invoice")
def get_invoice(invoice_id: str, caller: Caller = Depends(_caller)):
    """Get a purchase invoice with all line items by ID."""
    try:
        return _get_adapter(caller).get_invoice(invoice_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Invoice not found: {invoice_id}")


@app.post("/invoices", response_model=Invoice, status_code=201,
          summary="Create a new purchase invoice",
          operation_id="create_invoice")
def create_invoice(data: InvoiceCreate, caller: Caller = Depends(_caller)):
    """Create and submit a new purchase invoice."""
    return _get_adapter(caller).create_invoice(data)


@app.post("/invoices/extract", response_model=InvoiceExtractionResult,
          summary="Extract invoice data from a document in S3",
          operation_id="extract_invoice_document")
def extract_invoice_document(data: InvoiceExtractionRequest, caller: Caller = Depends(_caller)):
    """Extract structured invoice data from a PDF or image document stored in S3
    using Amazon Textract AnalyzeExpense. Returns vendor name, invoice number,
    dates, amounts, PO reference, line items, and confidence scores.

    Confidence tiers:
    - AUTO_ACCEPT (>=95%): all critical fields high confidence
    - REVIEW (80-95%): some fields uncertain, Bedrock validates
    - MANUAL (<80%): flag for human review
    """
    try:
        from services.textract import extract_invoice_from_s3
        result = extract_invoice_from_s3(data.bucket, data.key)
        return result
    except Exception as e:
        # nosemgrep -- logging-error-without-handling: best-effort demo path; failure is non-fatal and logged
        logger.error("Invoice extraction failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")


# --- Payments ---

@app.get("/payments", response_model=PaymentList,
         summary="List payment entries",
         operation_id="list_payments")
def list_payments(caller: Caller = Depends(_caller)):
    """List all payment entries."""
    return _get_adapter(caller).list_payments()


@app.post("/payments", response_model=Payment, status_code=201,
          summary="Create a new payment",
          operation_id="create_payment")
def create_payment(data: PaymentCreate, caller: Caller = Depends(_caller)):
    """Create and submit a new payment entry."""
    return _get_adapter(caller).create_payment(data)


# --- Analytics ---

@app.get("/analytics/spend-summary", response_model=SpendSummary,
         summary="Get spend analytics summary",
         operation_id="get_spend_summary")
def get_spend_summary(caller: Caller = Depends(_caller)):
    """Get aggregate procurement spend metrics: total spend, order counts, invoice counts, overdue items."""
    return _get_adapter(caller).get_spend_summary()


@app.get("/analytics/supplier-performance", response_model=SupplierPerformanceList,
         summary="Get supplier performance metrics",
         operation_id="get_supplier_performance")
def get_supplier_performance(caller: Caller = Depends(_caller)):
    """Get supplier performance data: order counts, total spend, delivery rates per supplier."""
    return _get_adapter(caller).get_supplier_performance()


@app.get("/analytics/budget-status",
         summary="Get budget status by cost center",
         operation_id="get_budget_status")
def get_budget_status(
    cost_center: Optional[str] = Query(None, description="Filter by cost center name"),
    caller: Caller = Depends(_caller),
):
    """Get budget vs actual spend for cost centers. Shows budget amount, actual spend, remaining, and utilization percentage."""
    adapter = _get_adapter(caller)
    try:
        return adapter.get_budget_status(cost_center=cost_center)
    except Exception:
        # Budget is a restricted doctype that per-user credentials often cannot
        # read. This is the one sanctioned service-account read: it is scoped to
        # company-level budget figures, is read-only, and the caller has already
        # been authenticated by _get_adapter above.
        logger.info("Per-user budget read failed; serving company budget via service account")
        return _build_service_adapter().get_budget_status(cost_center=cost_center)


@app.get("/cost-centers",
         summary="List cost centers",
         operation_id="list_cost_centers")
def list_cost_centers(caller: Caller = Depends(_caller)):
    """List available cost centers for budget allocation."""
    return _get_adapter(caller).list_cost_centers()


@app.get("/payment-terms",
         summary="List payment terms templates",
         operation_id="list_payment_terms")
def list_payment_terms(caller: Caller = Depends(_caller)):
    """List available payment terms templates (e.g. Net 30, 2/10 Net 30). Use exact names when creating purchase orders."""
    return _get_adapter(caller).list_payment_terms()


# ── File Attachments ─────────────────────────────────────────────────────────

@app.post("/attach", operation_id="attach_file")
async def attach_file(
    file: UploadFile = File(...),
    doctype: str = Form(...),
    docname: str = Form(...),
    is_private: str = Form("1"),
    caller: Caller = Depends(_caller),
):
    """Attach a file to an ERP document."""
    file_bytes = await file.read()
    adapter = _get_adapter(caller)
    return adapter.attach_file(docname, doctype, file_bytes, file.filename)


# ── Lambda handler: dual-mode (AgentCore Gateway MCP + API Gateway HTTP) ────

_mangum_handler = Mangum(app, api_gateway_base_path="/api/erp")


def _dispatch_tool(tool_name: str, params: dict, adapter: ERPAdapterBase):
    """Dispatch a Gateway MCP tool call to the appropriate adapter method."""
    handlers = {
        "list_suppliers":           lambda: adapter.list_suppliers(
                                        status=params.get("status"), group=params.get("group")),
        "get_supplier":             lambda: adapter.get_supplier(params["supplier_id"]),
        "list_items":               lambda: adapter.list_items(
                                        group=params.get("group"), search=params.get("search")),
        "get_item":                 lambda: adapter.get_item(params["item_id"]),
        "list_requisitions":        lambda: adapter.list_requisitions(
                                        status=params.get("status"), requester=params.get("requester")),
        "get_requisition":          lambda: adapter.get_requisition(params["requisition_id"]),
        "create_requisition":       lambda: adapter.create_requisition(
                                        RequisitionCreate(**params)),
        "list_purchase_orders":     lambda: adapter.list_purchase_orders(
                                        supplier_id=params.get("supplier_id"), status=params.get("status")),
        "get_purchase_order":       lambda: adapter.get_purchase_order(params["order_id"]),
        "create_purchase_order":    lambda: adapter.create_purchase_order(
                                        PurchaseOrderCreate(**params)),
        "list_receipts":            lambda: adapter.list_receipts(
                                        order_id=params.get("order_id")),
        "get_receipt":              lambda: adapter.get_receipt(params["receipt_id"]),
        "create_receipt":           lambda: adapter.create_receipt(
                                        ReceiptCreate(**params)),
        "list_invoices":            lambda: adapter.list_invoices(
                                        supplier_id=params.get("supplier_id"), status=params.get("status")),
        "get_invoice":              lambda: adapter.get_invoice(params["invoice_id"]),
        "create_invoice":           lambda: adapter.create_invoice(
                                        InvoiceCreate(**params)),
        "list_payments":            lambda: adapter.list_payments(),
        "create_payment":           lambda: adapter.create_payment(
                                        PaymentCreate(**params)),
        "get_spend_summary":        lambda: adapter.get_spend_summary(),
        "get_supplier_performance": lambda: adapter.get_supplier_performance(),
        "get_budget_status":        lambda: adapter.get_budget_status(
                                        cost_center=params.get("cost_center")),
        "list_cost_centers":        lambda: adapter.list_cost_centers(),
        "list_payment_terms":       lambda: adapter.list_payment_terms(),
    }
    fn = handlers.get(tool_name)
    if not fn:
        raise ValueError(f"Unknown tool: {tool_name}")
    return fn()


def handler(event, context):
    """Dual handler: AgentCore Gateway MCP tool calls + API Gateway HTTP requests."""
    # Check if this is an AgentCore Gateway MCP tool call
    # Gateway sends tool inputs as the event, tool name in context.client_context
    tool_name = None
    try:
        custom = context.client_context.custom if context.client_context else {}
        tool_name = custom.get("bedrockAgentCoreToolName", "")
    except (AttributeError, TypeError):
        # No client_context / custom attrs — not a Gateway MCP invocation.
        logger.debug("No AgentCore Gateway client_context on event; treating as HTTP request")

    if tool_name:
        # AgentCore Gateway MCP tool call — extract tool name after ___
        delimiter = "___"
        if delimiter in tool_name:
            tool_name = tool_name[tool_name.index(delimiter) + len(delimiter):]

        # Extract user_email from params for per-user ERP credential scoping.
        # Agents inject user_email into tool call params via prompt instructions.
        user_email = event.pop("user_email", None)

        logger.info("Gateway tool call: %s, user: %s, params: %s", tool_name, user_email, list(event.keys()))

        # The Gateway is an authenticated internal caller and agents may act on
        # system-initiated work with no end user, so the service account stays
        # available on this path.
        adapter = _get_adapter(Caller(email=user_email, allow_service_account=True))

        try:
            result = _dispatch_tool(tool_name, event, adapter)
            # Convert Pydantic models to dicts
            if hasattr(result, "model_dump"):
                return result.model_dump()
            if hasattr(result, "dict"):
                return result.dict()
            return result
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e)
            return {"error": str(e)}

    # Standard API Gateway HTTP event → Mangum/FastAPI
    return _mangum_handler(event, context)
