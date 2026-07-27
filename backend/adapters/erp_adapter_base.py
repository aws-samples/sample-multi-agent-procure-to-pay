# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Abstract ERP adapter interface.

Each ERP system implements this interface to provide canonical P2P operations.
The canonical_api.py FastAPI app delegates all requests to the active adapter.
"""

from abc import ABC, abstractmethod
from typing import Optional

from adapters.models import (
    Supplier, SupplierList,
    Item, ItemList,
    Requisition, RequisitionCreate, RequisitionList,
    PurchaseOrder, PurchaseOrderCreate, PurchaseOrderList,
    Receipt, ReceiptCreate, ReceiptList,
    Invoice, InvoiceCreate, InvoiceList,
    Payment, PaymentCreate, PaymentList,
    SpendSummary, SupplierPerformanceList,
)


class ERPAdapterBase(ABC):
    """Abstract interface for ERP P2P operations."""

    # --- Suppliers ---
    @abstractmethod
    def list_suppliers(self, status: Optional[str] = None,
                       group: Optional[str] = None) -> SupplierList: ...

    @abstractmethod
    def get_supplier(self, supplier_id: str) -> Supplier: ...

    # --- Items ---
    @abstractmethod
    def list_items(self, group: Optional[str] = None,
                   search: Optional[str] = None) -> ItemList: ...

    @abstractmethod
    def get_item(self, item_id: str) -> Item: ...

    # --- Requisitions ---
    @abstractmethod
    def list_requisitions(self, status: Optional[str] = None,
                          requester: Optional[str] = None,
                          detail: bool = True) -> RequisitionList: ...

    @abstractmethod
    def get_requisition(self, requisition_id: str) -> Requisition: ...

    @abstractmethod
    def create_requisition(self, data: RequisitionCreate) -> Requisition: ...

    # --- Purchase Orders ---
    @abstractmethod
    def list_purchase_orders(self, supplier_id: Optional[str] = None,
                             status: Optional[str] = None) -> PurchaseOrderList: ...

    @abstractmethod
    def get_purchase_order(self, order_id: str) -> PurchaseOrder: ...

    @abstractmethod
    def create_purchase_order(self, data: PurchaseOrderCreate) -> PurchaseOrder: ...

    # --- Receipts ---
    @abstractmethod
    def list_receipts(self, order_id: Optional[str] = None) -> ReceiptList: ...

    @abstractmethod
    def get_receipt(self, receipt_id: str) -> Receipt: ...

    @abstractmethod
    def create_receipt(self, data: ReceiptCreate) -> Receipt: ...

    # --- Invoices ---
    @abstractmethod
    def list_invoices(self, supplier_id: Optional[str] = None,
                      status: Optional[str] = None) -> InvoiceList: ...

    @abstractmethod
    def get_invoice(self, invoice_id: str) -> Invoice: ...

    @abstractmethod
    def create_invoice(self, data: InvoiceCreate) -> Invoice: ...

    # --- Payments ---
    @abstractmethod
    def list_payments(self) -> PaymentList: ...

    @abstractmethod
    def create_payment(self, data: PaymentCreate) -> Payment: ...

    # --- Analytics ---
    @abstractmethod
    def get_spend_summary(self) -> SpendSummary: ...

    @abstractmethod
    def get_supplier_performance(self) -> SupplierPerformanceList: ...

    @abstractmethod
    def get_budget_status(self, cost_center: Optional[str] = None) -> "BudgetStatusList": ...

    @abstractmethod
    def list_cost_centers(self) -> "CostCenterList": ...

    # --- File Attachments ---
    def attach_file(self, docname: str, doctype: str, file_bytes: bytes, filename: str) -> dict:
        """Attach a file to an ERP document. Optional — not all adapters support this."""
        raise NotImplementedError("File attachment not supported by this adapter")
