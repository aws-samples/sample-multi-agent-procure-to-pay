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


# --- Payment Tests ---

import requests
from adapters.errors import DuplicatePaymentError, PaymentNotPostedError
from adapters.models import PaymentCreate


def _http_error(status: int) -> requests.exceptions.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.exceptions.HTTPError(f"HTTP {status}", response=resp)


POSTED = {"name": "PE-001", "docstatus": 1, "status": "Submitted", "party": "SUP-001",
          "paid_amount": 2700.0, "mode_of_payment": "Wire Transfer"}
DRAFT = {**POSTED, "docstatus": 0, "status": "Draft"}
PAY = PaymentCreate(supplier_id="SUP-001", amount=2700.0, invoice_id="PINV-001")


class TestCreatePayment:
    """A normal return means posted. Everything else raises."""

    def test_posted_payment_returns_submitted(self, adapter, mock_client):
        mock_client.get_list.return_value = []                                # no existing payment
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, POSTED]  # invoice, then re-read
        mock_client.insert.return_value = {"name": "PE-001"}
        mock_client.submit.return_value = {"docstatus": 1}

        result = adapter.create_payment(PAY)

        assert result.payment_id == "PE-001"
        assert result.status == "submitted"
        mock_client.submit.assert_called_once_with("Payment Entry", "PE-001")
        # Allocation uses the invoice's real outstanding amount.
        assert mock_client.insert.call_args[0][1]["references"][0]["allocated_amount"] == 2700.0

    def test_rejected_submit_raises_not_returns_draft(self, adapter, mock_client):
        """Issue #91 point 1: a failed submit used to be a warning and a normal return."""
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, DRAFT]
        mock_client.insert.return_value = {"name": "PE-001"}
        mock_client.submit.side_effect = _http_error(417)  # ERPNext ValidationError

        with pytest.raises(PaymentNotPostedError) as exc:
            adapter.create_payment(PAY)
        assert exc.value.outcome == "rejected"
        assert exc.value.payment_id == "PE-001"

    @pytest.mark.parametrize("failure", [
        requests.exceptions.Timeout("read timed out"),
        requests.exceptions.ConnectionError("connection reset"),
        _http_error(502),
    ])
    def test_indeterminate_submit_is_unknown_not_rejected(self, adapter, mock_client, failure):
        """Issue #91 point 2: timeout/5xx says nothing about whether it posted."""
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, DRAFT]
        mock_client.insert.return_value = {"name": "PE-001"}
        mock_client.submit.side_effect = failure

        with pytest.raises(PaymentNotPostedError) as exc:
            adapter.create_payment(PAY)
        assert exc.value.outcome == "unknown"

    def test_unknown_submit_resolved_by_reread_as_posted(self, adapter, mock_client):
        """The re-read is authoritative: a timed-out submit that did apply is a success."""
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, POSTED]
        mock_client.insert.return_value = {"name": "PE-001"}
        mock_client.submit.side_effect = requests.exceptions.Timeout("read timed out")

        result = adapter.create_payment(PAY)
        assert result.status == "submitted"

    def test_submit_ok_but_entry_still_draft_raises(self, adapter, mock_client):
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, DRAFT]
        mock_client.insert.return_value = {"name": "PE-001"}
        mock_client.submit.return_value = {}

        with pytest.raises(PaymentNotPostedError) as exc:
            adapter.create_payment(PAY)
        assert exc.value.outcome == "unknown"

    def test_reread_failure_after_submit_is_unknown(self, adapter, mock_client):
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, requests.exceptions.ConnectionError("down")]
        mock_client.insert.return_value = {"name": "PE-001"}
        mock_client.submit.return_value = {}

        with pytest.raises(PaymentNotPostedError) as exc:
            adapter.create_payment(PAY)
        assert exc.value.outcome == "unknown"

    def test_invoice_read_failure_aborts_before_insert(self, adapter, mock_client):
        """Issue #91 smaller point: no silent fallback to the caller-supplied amount."""
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = requests.exceptions.ConnectionError("down")

        with pytest.raises(ValueError, match="Cannot read Purchase Invoice"):
            adapter.create_payment(PAY)
        mock_client.insert.assert_not_called()

    def test_insert_conflict_raises(self, adapter, mock_client):
        mock_client.get_list.return_value = []
        mock_client.get.return_value = {"outstanding_amount": 2700.0}
        mock_client.insert.return_value = {}

        with pytest.raises(ValueError, match="Failed to create payment"):
            adapter.create_payment(PAY)
        mock_client.submit.assert_not_called()


class TestCreatePaymentIdempotency:
    """Issue #91 point 3: a retry must never produce a second Payment Entry."""

    def test_existing_posted_payment_blocks_insert(self, adapter, mock_client):
        mock_client.get_list.return_value = [{"name": "PE-001", "docstatus": 1, "status": "Submitted"}]

        with pytest.raises(DuplicatePaymentError) as exc:
            adapter.create_payment(PAY)
        assert exc.value.existing_payment_id == "PE-001"
        assert exc.value.existing_status == "submitted"
        mock_client.insert.assert_not_called()

    def test_existing_draft_blocks_insert(self, adapter, mock_client):
        mock_client.get_list.return_value = [{"name": "PE-001", "docstatus": 0, "status": "Draft"}]

        with pytest.raises(DuplicatePaymentError) as exc:
            adapter.create_payment(PAY)
        assert exc.value.existing_status == "draft"
        assert "unposted draft" in str(exc.value)
        mock_client.insert.assert_not_called()

    def test_posted_reported_over_draft_when_both_exist(self, adapter, mock_client):
        mock_client.get_list.return_value = [
            {"name": "PE-002", "docstatus": 0},
            {"name": "PE-001", "docstatus": 1},
        ]
        with pytest.raises(DuplicatePaymentError) as exc:
            adapter.create_payment(PAY)
        assert exc.value.existing_payment_id == "PE-001"

    def test_dedup_query_targets_invoice_reference_and_excludes_cancelled(self, adapter, mock_client):
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, POSTED]
        mock_client.insert.return_value = {"name": "PE-001"}

        adapter.create_payment(PAY)

        filters = mock_client.get_list.call_args[1]["filters"]
        assert ["Payment Entry Reference", "reference_name", "=", "PINV-001"] in filters
        assert ["docstatus", "<", 2] in filters

    def test_dedup_check_failure_refuses_to_pay(self, adapter, mock_client):
        """'Could not verify' must not become 'paid twice'."""
        mock_client.get_list.side_effect = requests.exceptions.ConnectionError("down")

        with pytest.raises(ValueError, match="Cannot verify existing payments"):
            adapter.create_payment(PAY)
        mock_client.insert.assert_not_called()

    def test_retry_after_unknown_outcome_is_blocked(self, adapter, mock_client):
        """The scenario from the issue end to end: first call times out on submit
        and the re-read shows a draft; the natural retry must be refused."""
        mock_client.get_list.return_value = []
        mock_client.get.side_effect = [{"outstanding_amount": 2700.0}, DRAFT]
        mock_client.insert.return_value = {"name": "PE-001"}
        mock_client.submit.side_effect = requests.exceptions.Timeout("read timed out")
        with pytest.raises(PaymentNotPostedError):
            adapter.create_payment(PAY)

        # Operator / agent retries. The draft from the first attempt now exists.
        mock_client.get_list.return_value = [{"name": "PE-001", "docstatus": 0}]
        with pytest.raises(DuplicatePaymentError):
            adapter.create_payment(PAY)
        assert mock_client.insert.call_count == 1

    def test_no_invoice_id_skips_dedup(self, adapter, mock_client):
        """Unreferenced payments (no invoice) have no idempotency key; unchanged behaviour."""
        mock_client.get.return_value = POSTED
        mock_client.insert.return_value = {"name": "PE-001"}

        result = adapter.create_payment(PaymentCreate(supplier_id="SUP-001", amount=100.0))
        assert result.status == "submitted"
        mock_client.get_list.assert_not_called()
