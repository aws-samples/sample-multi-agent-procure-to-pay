# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for ERPNext <-> Canonical field mapping."""

import pytest
from adapters.erpnext.field_maps import (
    map_record, map_records, map_status_to_canonical,
    SUPPLIER_TO_CANONICAL, ITEM_TO_CANONICAL,
    REQUISITION_TO_CANONICAL, REQUISITION_ITEM_TO_CANONICAL,
    PO_TO_CANONICAL, PO_ITEM_TO_CANONICAL,
    RECEIPT_TO_CANONICAL, RECEIPT_ITEM_TO_CANONICAL,
    INVOICE_TO_CANONICAL, INVOICE_ITEM_TO_CANONICAL,
    PAYMENT_TO_CANONICAL,
)


class TestMapRecord:
    def test_maps_known_fields(self):
        record = {"name": "SUP-001", "supplier_name": "Acme Corp", "country": "US"}
        result = map_record(record, SUPPLIER_TO_CANONICAL)
        assert result == {
            "supplier_id": "SUP-001",
            "supplier_name": "Acme Corp",
            "country": "US",
        }

    def test_ignores_unmapped_fields(self):
        record = {"name": "SUP-001", "custom_field": "ignored"}
        result = map_record(record, SUPPLIER_TO_CANONICAL)
        assert "custom_field" not in result
        assert result["supplier_id"] == "SUP-001"

    def test_handles_empty_record(self):
        assert map_record({}, SUPPLIER_TO_CANONICAL) == {}

    def test_handles_none_values(self):
        record = {"name": "SUP-001", "supplier_name": None}
        result = map_record(record, SUPPLIER_TO_CANONICAL)
        assert result["supplier_name"] is None


class TestMapRecords:
    def test_maps_list(self):
        records = [
            {"name": "SUP-001", "supplier_name": "Acme"},
            {"name": "SUP-002", "supplier_name": "Beta"},
        ]
        results = map_records(records, SUPPLIER_TO_CANONICAL)
        assert len(results) == 2
        assert results[0]["supplier_id"] == "SUP-001"
        assert results[1]["supplier_id"] == "SUP-002"

    def test_empty_list(self):
        assert map_records([], SUPPLIER_TO_CANONICAL) == []


class TestMapStatusToCanonical:
    @pytest.mark.parametrize("erpnext_status,expected", [
        ("Draft", "draft"),
        ("Pending", "pending_approval"),
        ("Ordered", "ordered"),
        ("Cancelled", "cancelled"),
    ])
    def test_material_request_statuses(self, erpnext_status, expected):
        assert map_status_to_canonical(erpnext_status, "Material Request") == expected

    @pytest.mark.parametrize("erpnext_status,expected", [
        ("Draft", "draft"),
        ("To Receive and Bill", "submitted"),
        ("Completed", "completed"),
        ("Cancelled", "cancelled"),
        ("Closed", "closed"),
    ])
    def test_purchase_order_statuses(self, erpnext_status, expected):
        assert map_status_to_canonical(erpnext_status, "Purchase Order") == expected

    @pytest.mark.parametrize("erpnext_status,expected", [
        ("Unpaid", "unpaid"),
        ("Paid", "paid"),
        ("Overdue", "overdue"),
        ("Return", "return"),
    ])
    def test_purchase_invoice_statuses(self, erpnext_status, expected):
        assert map_status_to_canonical(erpnext_status, "Purchase Invoice") == expected

    def test_unknown_status_lowercased(self):
        result = map_status_to_canonical("Some New Status", "Purchase Order")
        assert result == "some_new_status"

    def test_unknown_doctype_lowercased(self):
        result = map_status_to_canonical("Active", "Unknown Doctype")
        assert result == "active"


class TestFieldMapCompleteness:
    """Verify all field maps contain expected key mappings."""

    def test_supplier_map_has_id(self):
        assert "name" in SUPPLIER_TO_CANONICAL
        assert SUPPLIER_TO_CANONICAL["name"] == "supplier_id"

    def test_item_map_has_id(self):
        assert "item_code" in ITEM_TO_CANONICAL
        assert ITEM_TO_CANONICAL["item_code"] == "item_id"

    def test_requisition_map_has_id(self):
        assert "name" in REQUISITION_TO_CANONICAL
        assert REQUISITION_TO_CANONICAL["name"] == "requisition_id"

    def test_po_map_has_id(self):
        assert "name" in PO_TO_CANONICAL
        assert PO_TO_CANONICAL["name"] == "order_id"

    def test_receipt_map_has_id(self):
        assert "name" in RECEIPT_TO_CANONICAL
        assert RECEIPT_TO_CANONICAL["name"] == "receipt_id"

    def test_invoice_map_has_id(self):
        assert "name" in INVOICE_TO_CANONICAL
        assert INVOICE_TO_CANONICAL["name"] == "invoice_id"

    def test_payment_map_has_id(self):
        assert "name" in PAYMENT_TO_CANONICAL
        assert PAYMENT_TO_CANONICAL["name"] == "payment_id"

    def test_po_item_map_has_line_number(self):
        assert "idx" in PO_ITEM_TO_CANONICAL
        assert PO_ITEM_TO_CANONICAL["idx"] == "line_number"

    def test_invoice_item_map_has_order_ref(self):
        assert "purchase_order" in INVOICE_ITEM_TO_CANONICAL
        assert INVOICE_ITEM_TO_CANONICAL["purchase_order"] == "order_id"
