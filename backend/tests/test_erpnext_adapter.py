# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ERPNext adapter with mocked client."""

import pytest
from unittest.mock import MagicMock, patch
from adapters.erpnext.adapter import ERPNextAdapter
from adapters.models import SupplierList, ItemList, PurchaseOrderList, InvoiceList


@pytest.fixture
def mock_client():
    """Create a mock ERPNextClient."""
    client = MagicMock()
    return client


@pytest.fixture
def adapter(mock_client):
    """Create adapter with mocked client."""
    return ERPNextAdapter(mock_client)


# --- Supplier Tests ---

class TestListSuppliers:
    def test_returns_canonical_format(self, adapter, mock_client):
        mock_client.get_list.return_value = [
            {"name": "SUP-001", "supplier_name": "Acme Corp", "supplier_group": "Raw Material", "country": "US"},
            {"name": "SUP-002", "supplier_name": "Beta Inc", "supplier_group": "Services", "country": "UK"},
        ]
        result = adapter.list_suppliers()
        assert isinstance(result, SupplierList)
        assert result.total_count == 2
        assert result.suppliers[0].supplier_id == "SUP-001"
        assert result.suppliers[0].supplier_name == "Acme Corp"
        assert result.suppliers[1].supplier_id == "SUP-002"

    def test_filters_by_group(self, adapter, mock_client):
        mock_client.get_list.return_value = []
        adapter.list_suppliers(group="Raw Material")
        mock_client.get_list.assert_called_once()
        call_args = mock_client.get_list.call_args
        assert call_args[1]["filters"] == [["supplier_group", "=", "Raw Material"]]

    def test_empty_list(self, adapter, mock_client):
        mock_client.get_list.return_value = []
        result = adapter.list_suppliers()
        assert result.total_count == 0
        assert result.suppliers == []


class TestGetSupplier:
    def test_returns_canonical_supplier(self, adapter, mock_client):
        mock_client.get.return_value = {
            "name": "SUP-001", "supplier_name": "Acme Corp",
            "country": "US", "default_currency": "USD",
        }
        result = adapter.get_supplier("SUP-001")
        assert result.supplier_id == "SUP-001"
        assert result.supplier_name == "Acme Corp"
        mock_client.get.assert_called_with("Supplier", "SUP-001")


# --- Item Tests ---

class TestListItems:
    def test_returns_canonical_items(self, adapter, mock_client):
        mock_client.get_list.return_value = [
            {"item_code": "BRG-001", "item_name": "Ball Bearing", "item_group": "Bearings", "stock_uom": "Nos"},
        ]
        result = adapter.list_items()
        assert isinstance(result, ItemList)
        assert result.items[0].item_id == "BRG-001"
        assert result.items[0].item_name == "Ball Bearing"

    def test_search_filter(self, adapter, mock_client):
        mock_client.get_list.return_value = []
        adapter.list_items(search="bearing")
        call_args = mock_client.get_list.call_args
        assert any("like" in f for f in call_args[1].get("filters", []))


# --- Purchase Order Tests ---

class TestListPurchaseOrders:
    def test_returns_canonical_orders(self, adapter, mock_client):
        mock_client.get_list.return_value = [
            {"name": "PO-001", "supplier": "SUP-001", "supplier_name": "Acme",
             "status": "To Receive and Bill", "grand_total": 5000.0,
             "transaction_date": "2026-01-15", "currency": "USD"},
        ]
        result = adapter.list_purchase_orders()
        assert isinstance(result, PurchaseOrderList)
        assert result.purchase_orders[0].order_id == "PO-001"
        assert result.purchase_orders[0].supplier_id == "SUP-001"
        assert result.purchase_orders[0].status == "submitted"
        assert result.purchase_orders[0].total_amount == 5000.0


class TestGetPurchaseOrder:
    def test_returns_with_line_items(self, adapter, mock_client):
        mock_client.get.return_value = {
            "name": "PO-001", "supplier": "SUP-001", "supplier_name": "Acme",
            "status": "To Receive and Bill", "grand_total": 900.0,
            "transaction_date": "2026-01-15", "currency": "USD",
            "items": [
                {"idx": 1, "item_code": "BRG-001", "item_name": "Bearing",
                 "qty": 10, "rate": 45.0, "amount": 450.0, "stock_uom": "Nos"},
                {"idx": 2, "item_code": "BRG-002", "item_name": "Seal",
                 "qty": 20, "rate": 22.5, "amount": 450.0, "stock_uom": "Nos"},
            ],
        }
        result = adapter.get_purchase_order("PO-001")
        assert result.order_id == "PO-001"
        assert len(result.line_items) == 2
        assert result.line_items[0].item_id == "BRG-001"
        assert result.line_items[0].quantity == 10
        assert result.line_items[1].unit_price == 22.5


# --- Invoice Tests ---

class TestListInvoices:
    def test_returns_canonical_invoices(self, adapter, mock_client):
        mock_client.get_list.return_value = [
            {"name": "PINV-001", "supplier": "SUP-001", "supplier_name": "Acme",
             "status": "Unpaid", "grand_total": 5000.0, "outstanding_amount": 5000.0,
             "posting_date": "2026-02-01", "currency": "USD"},
        ]
        result = adapter.list_invoices()
        assert isinstance(result, InvoiceList)
        assert result.invoices[0].invoice_id == "PINV-001"
        assert result.invoices[0].status == "unpaid"


# --- Spend Summary Tests ---

class TestSpendSummary:
    def test_aggregates_counts(self, adapter, mock_client):
        mock_client.get_count.side_effect = [25, 20, 80, 5, 3, 1]  # orders, invoices, suppliers, open, unpaid, overdue
        mock_client.get_list.return_value = [{"total": 150000.0}]
        result = adapter.get_spend_summary()
        assert result.total_orders == 25
        assert result.total_invoices == 20
        assert result.total_suppliers == 80
        assert result.total_spend == 150000.0


# --- Supplier Performance Tests ---

class TestSupplierPerformance:
    def test_returns_performance_data(self, adapter, mock_client):
        mock_client.get_list.return_value = [
            {"supplier": "SUP-001", "supplier_name": "Acme", "order_count": 10, "total_spend": 50000.0},
            {"supplier": "SUP-002", "supplier_name": "Beta", "order_count": 5, "total_spend": 25000.0},
        ]
        result = adapter.get_supplier_performance()
        assert result.total_count == 2
        assert result.suppliers[0].supplier_id == "SUP-001"
        assert result.suppliers[0].total_spend == 50000.0
