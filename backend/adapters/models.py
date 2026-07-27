# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Canonical P2P data models.

Domain-standard naming: supplier_id, order_id, requisition_id, etc.
No SAP (LIFNR, EBELN) or ERPNext (supplier_name, name) specific terminology.
All dates ISO 8601. All amounts float with explicit currency field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# --- Enums ---

class SupplierStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    INACTIVE = "inactive"


class RequisitionStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDERED = "ordered"
    CANCELLED = "cancelled"


class OrderStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    TO_RECEIVE = "to_receive"
    TO_BILL = "to_bill"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    RETURN = "return"


class PaymentStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


# --- Supplier ---

class Supplier(BaseModel):
    supplier_id: str = Field(description="Unique supplier identifier")
    supplier_name: str = Field(description="Supplier display name")
    supplier_group: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    default_currency: str = "USD"
    payment_terms: Optional[str] = None
    tax_id: Optional[str] = None
    status: SupplierStatus = SupplierStatus.ACTIVE
    website: Optional[str] = None
    primary_contact_name: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None


class SupplierList(BaseModel):
    suppliers: list[Supplier]
    total_count: int


# --- Item (Material) ---

class Item(BaseModel):
    item_id: str = Field(description="Unique item/material identifier")
    item_name: str = Field(description="Item display name")
    item_group: Optional[str] = None
    unit_of_measure: str = "Nos"
    standard_price: Optional[float] = None
    currency: str = "USD"
    description: Optional[str] = None
    is_stock_item: bool = True


class ItemList(BaseModel):
    items: list[Item]
    total_count: int


# --- Requisition (Material Request) ---

class RequisitionLineItem(BaseModel):
    line_number: int = 0
    item_id: str
    item_name: Optional[str] = None
    quantity: float
    unit_of_measure: str = "Nos"
    unit_price: Optional[float] = None
    currency: str = "USD"
    delivery_date: Optional[str] = None
    preferred_supplier_id: Optional[str] = None
    warehouse: Optional[str] = None


class Requisition(BaseModel):
    requisition_id: str = Field(description="Unique requisition identifier")
    status: RequisitionStatus = RequisitionStatus.DRAFT
    requester: Optional[str] = None
    department: Optional[str] = None
    cost_center: Optional[str] = None
    created_date: Optional[str] = None
    required_date: Optional[str] = None
    total_amount: Optional[float] = None
    currency: str = "USD"
    purpose: Optional[str] = None
    line_items: list[RequisitionLineItem] = []


class RequisitionCreate(BaseModel):
    """Input model for creating a requisition."""
    required_date: Optional[str] = None
    purpose: Optional[str] = None
    department: Optional[str] = None
    cost_center: Optional[str] = None
    line_items: list[RequisitionLineItem]


class RequisitionList(BaseModel):
    requisitions: list[Requisition]
    total_count: int


# --- Purchase Order ---

class PurchaseOrderLineItem(BaseModel):
    line_number: int
    item_id: str
    item_name: Optional[str] = None
    quantity: float
    unit_of_measure: str = "Nos"
    unit_price: float
    line_amount: float
    delivery_date: Optional[str] = None
    received_quantity: Optional[float] = 0.0
    billed_amount: Optional[float] = 0.0
    requisition_id: Optional[str] = None
    warehouse: Optional[str] = None


class PurchaseOrder(BaseModel):
    order_id: str = Field(description="Unique purchase order identifier")
    supplier_id: str
    supplier_name: Optional[str] = None
    status: OrderStatus = OrderStatus.DRAFT
    order_date: Optional[str] = None
    delivery_date: Optional[str] = None
    total_amount: Optional[float] = None
    currency: str = "USD"
    payment_terms: Optional[str] = None
    requisition_id: Optional[str] = None
    line_items: list[PurchaseOrderLineItem] = []


class PurchaseOrderCreate(BaseModel):
    """Input model for creating a purchase order."""
    supplier_id: str
    delivery_date: Optional[str] = None
    payment_terms: Optional[str] = None
    line_items: list[PurchaseOrderLineItem]


class PurchaseOrderList(BaseModel):
    purchase_orders: list[PurchaseOrder]
    total_count: int


# --- Receipt (Goods Receipt / Purchase Receipt) ---

class ReceiptLineItem(BaseModel):
    line_number: int
    item_id: str
    item_name: Optional[str] = None
    quantity_received: float
    unit_of_measure: str = "Nos"
    rejected_quantity: Optional[float] = 0.0
    order_id: Optional[str] = None


class Receipt(BaseModel):
    receipt_id: str = Field(description="Unique goods receipt identifier")
    order_id: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    receipt_date: Optional[str] = None
    posting_date: Optional[str] = None
    status: Optional[str] = None
    line_items: list[ReceiptLineItem] = []


class ReceiptCreate(BaseModel):
    """Input model for creating a goods receipt."""
    order_id: str
    supplier_id: str
    line_items: list[ReceiptLineItem]


class ReceiptList(BaseModel):
    receipts: list[Receipt]
    total_count: int


# --- Invoice (Purchase Invoice) ---

class InvoiceLineItem(BaseModel):
    line_number: int
    item_id: str
    item_name: Optional[str] = None
    quantity: float
    unit_price: float
    line_amount: float
    order_id: Optional[str] = None
    receipt_id: Optional[str] = None


class Invoice(BaseModel):
    invoice_id: str = Field(description="Unique invoice identifier")
    supplier_id: str
    supplier_name: Optional[str] = None
    vendor_invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    posting_date: Optional[str] = None
    total_amount: Optional[float] = None
    outstanding_amount: Optional[float] = None
    currency: str = "USD"
    payment_terms: Optional[str] = None
    status: InvoiceStatus = InvoiceStatus.DRAFT
    order_id: Optional[str] = None
    line_items: list[InvoiceLineItem] = []


class InvoiceCreate(BaseModel):
    """Input model for creating an invoice."""
    supplier_id: str
    vendor_invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    order_id: Optional[str] = None
    line_items: list[InvoiceLineItem]


class InvoiceList(BaseModel):
    invoices: list[Invoice]
    total_count: int


# --- Payment ---

class Payment(BaseModel):
    payment_id: str = Field(description="Unique payment identifier")
    payment_type: str = "Pay"
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    amount: float
    currency: str = "USD"
    payment_date: Optional[str] = None
    mode_of_payment: Optional[str] = None
    reference_number: Optional[str] = None
    status: PaymentStatus = PaymentStatus.DRAFT
    invoices: list[str] = Field(default_factory=list, description="List of invoice_ids")


class PaymentDeduction(BaseModel):
    """Deduction line for early payment discounts, write-offs, etc."""
    account: str = "Write Off - AMG"
    cost_center: str = "Main - AMG"
    amount: float = 0.0

class PaymentCreate(BaseModel):
    """Input model for creating a payment.

    For early payment discounts: set amount to the net payment, and add a
    deduction entry for the discount amount with the appropriate account.
    The adapter will allocate the full invoice outstanding and balance via deductions.
    """
    supplier_id: str
    amount: float
    mode_of_payment: Optional[str] = "Wire Transfer"
    invoice_id: Optional[str] = None
    deductions: Optional[list[PaymentDeduction]] = None


class PaymentList(BaseModel):
    payments: list[Payment]
    total_count: int


# --- Invoice Extraction (Textract) ---

class InvoiceExtractionRequest(BaseModel):
    """Request to extract invoice data from a document in S3."""
    bucket: str = Field(description="S3 bucket containing the invoice document")
    key: str = Field(description="S3 object key (file path) of the invoice PDF or image")


class InvoiceExtractionResult(BaseModel):
    """Structured data extracted from an invoice document with confidence scores."""
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    total_amount: Optional[float] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    po_number: Optional[str] = None
    currency: Optional[str] = None
    payment_terms: Optional[str] = None
    vendor_address: Optional[str] = None
    receiver_name: Optional[str] = None
    line_items: list[dict] = Field(default_factory=list)
    confidence: dict = Field(default_factory=dict, description="Confidence assessment with tier: AUTO_ACCEPT/REVIEW/MANUAL")
    bedrock_corrections: Optional[dict] = Field(default=None, description="Corrections applied by Bedrock validation (if any)")
    raw_fields: dict = Field(default_factory=dict, description="Raw Textract field extractions with confidence scores")


# --- Analytics ---

class SpendSummary(BaseModel):
    total_spend: float
    total_orders: int
    total_invoices: int
    total_suppliers: int
    open_orders: int
    unpaid_invoices: int
    overdue_invoices: int
    currency: str = "USD"


class SupplierPerformance(BaseModel):
    supplier_id: str
    supplier_name: str
    total_orders: int
    total_spend: float
    on_time_delivery_rate: Optional[float] = None
    quality_score: Optional[float] = None
    currency: str = "USD"


class SupplierPerformanceList(BaseModel):
    suppliers: list[SupplierPerformance]
    total_count: int


class BudgetStatus(BaseModel):
    cost_center: str
    cost_center_name: str
    fiscal_year: str
    budget_amount: float
    actual_spend: float
    remaining: float
    utilization_pct: float
    exceeded: bool
    currency: str = "USD"


class BudgetStatusList(BaseModel):
    budgets: list[BudgetStatus]
    total_count: int


class CostCenter(BaseModel):
    cost_center_id: str
    cost_center_name: str
    parent: Optional[str] = None


class CostCenterList(BaseModel):
    cost_centers: list[CostCenter]
    total_count: int
