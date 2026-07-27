# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for canonical P2P data models."""

import pytest
from pydantic import ValidationError
from adapters.models import (
    Supplier, SupplierStatus, SupplierList,
    Item, ItemList,
    Requisition, RequisitionStatus, RequisitionCreate, RequisitionLineItem,
    PurchaseOrder, OrderStatus, PurchaseOrderLineItem,
    Receipt, ReceiptLineItem,
    Invoice, InvoiceStatus, InvoiceLineItem,
    Payment, PaymentStatus,
    SpendSummary, SupplierPerformance,
)


class TestSupplier:
    def test_valid_supplier(self):
        s = Supplier(supplier_id="SUP-001", supplier_name="Acme Corp")
        assert s.supplier_id == "SUP-001"
        assert s.status == SupplierStatus.ACTIVE  # default

    def test_all_fields(self):
        s = Supplier(
            supplier_id="SUP-001", supplier_name="Acme Corp",
            country="US", city="New York", region="NY",
            supplier_group="Raw Material", payment_terms="Net 30",
            default_currency="USD", status="blocked",
        )
        assert s.status == SupplierStatus.BLOCKED

    def test_supplier_list(self):
        sl = SupplierList(
            suppliers=[Supplier(supplier_id="S1", supplier_name="A")],
            total_count=1,
        )
        assert sl.total_count == 1


class TestItem:
    def test_valid_item(self):
        i = Item(item_id="ITM-001", item_name="Bearing")
        assert i.unit_of_measure == "Nos"  # default
        assert i.currency == "USD"

    def test_with_price(self):
        i = Item(item_id="ITM-001", item_name="Bearing", standard_price=45.50)
        assert i.standard_price == 45.50


class TestRequisition:
    def test_valid_requisition(self):
        r = Requisition(requisition_id="MAT-REQ-001")
        assert r.status == RequisitionStatus.DRAFT
        assert r.line_items == []

    def test_with_line_items(self):
        li = RequisitionLineItem(
            line_number=1, item_id="ITM-001", quantity=10.0,
        )
        r = Requisition(requisition_id="MAT-REQ-001", line_items=[li])
        assert len(r.line_items) == 1
        assert r.line_items[0].item_id == "ITM-001"

    def test_create_model(self):
        li = RequisitionLineItem(line_number=1, item_id="ITM-001", quantity=5.0)
        rc = RequisitionCreate(line_items=[li])
        assert len(rc.line_items) == 1


class TestPurchaseOrder:
    def test_valid_po(self):
        po = PurchaseOrder(
            order_id="PO-001", supplier_id="SUP-001",
        )
        assert po.status == OrderStatus.DRAFT

    def test_with_line_items(self):
        li = PurchaseOrderLineItem(
            line_number=1, item_id="ITM-001", quantity=10.0,
            unit_price=45.0, line_amount=450.0,
        )
        po = PurchaseOrder(
            order_id="PO-001", supplier_id="SUP-001",
            line_items=[li], total_amount=450.0,
        )
        assert po.line_items[0].line_amount == 450.0


class TestReceipt:
    def test_valid_receipt(self):
        r = Receipt(receipt_id="PREC-001")
        assert r.line_items == []

    def test_with_items(self):
        li = ReceiptLineItem(
            line_number=1, item_id="ITM-001", quantity_received=8.0,
        )
        r = Receipt(receipt_id="PREC-001", order_id="PO-001", line_items=[li])
        assert r.line_items[0].quantity_received == 8.0


class TestInvoice:
    def test_valid_invoice(self):
        inv = Invoice(invoice_id="PINV-001", supplier_id="SUP-001")
        assert inv.status == InvoiceStatus.DRAFT

    def test_with_line_items(self):
        li = InvoiceLineItem(
            line_number=1, item_id="ITM-001",
            quantity=10.0, unit_price=45.0, line_amount=450.0,
        )
        inv = Invoice(
            invoice_id="PINV-001", supplier_id="SUP-001",
            line_items=[li], total_amount=450.0,
        )
        assert inv.line_items[0].line_amount == 450.0


class TestPayment:
    def test_valid_payment(self):
        p = Payment(payment_id="PAY-001", amount=1000.0)
        assert p.status == PaymentStatus.DRAFT
        assert p.currency == "USD"


class TestSpendSummary:
    def test_valid_summary(self):
        s = SpendSummary(
            total_spend=50000.0, total_orders=25, total_invoices=20,
            total_suppliers=10, open_orders=5, unpaid_invoices=3,
            overdue_invoices=1,
        )
        assert s.total_spend == 50000.0


class TestEnums:
    def test_supplier_status_values(self):
        assert set(SupplierStatus) == {"active", "blocked", "inactive"}

    def test_requisition_status_values(self):
        assert "draft" in set(RequisitionStatus)
        assert "approved" in set(RequisitionStatus)
        assert "rejected" in set(RequisitionStatus)

    def test_order_status_values(self):
        assert "submitted" in set(OrderStatus)
        assert "completed" in set(OrderStatus)

    def test_invoice_status_values(self):
        assert "unpaid" in set(InvoiceStatus)
        assert "paid" in set(InvoiceStatus)
        assert "overdue" in set(InvoiceStatus)
