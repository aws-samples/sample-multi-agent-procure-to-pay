# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
ERPNext <-> Canonical field mapping dictionaries.

Explicit, auditable mappings. Each dict maps ERPNext field names to canonical names.
Adding a new ERP means creating a similar file with that ERP's field mappings.
"""

# --- Supplier ---
# ERPNext Supplier doctype -> Canonical Supplier
SUPPLIER_TO_CANONICAL = {
    "name": "supplier_id",
    "supplier_name": "supplier_name",
    "supplier_group": "supplier_group",
    "country": "country",
    "default_currency": "default_currency",
    "tax_id": "tax_id",
    "website": "website",
    "payment_terms": "payment_terms",
}

SUPPLIER_LIST_FIELDS = [
    "name", "supplier_name", "supplier_group", "country",
    "default_currency", "tax_id", "website",
]

# --- Item ---
# ERPNext Item doctype -> Canonical Item
ITEM_TO_CANONICAL = {
    "item_code": "item_id",
    "item_name": "item_name",
    "item_group": "item_group",
    "stock_uom": "unit_of_measure",
    "standard_rate": "standard_price",
    "description": "description",
    "is_stock_item": "is_stock_item",
}

ITEM_LIST_FIELDS = [
    "item_code", "item_name", "item_group", "stock_uom",
    "standard_rate", "description", "is_stock_item",
]

# --- Material Request (Requisition) ---
REQUISITION_TO_CANONICAL = {
    "name": "requisition_id",
    "status": "status",
    "owner": "requester",
    "department": "department",
    "cost_center": "cost_center",
    "creation": "created_date",
    "schedule_date": "required_date",
    "grand_total": "total_amount",
    "currency": "currency",
}

REQUISITION_ITEM_TO_CANONICAL = {
    "idx": "line_number",
    "item_code": "item_id",
    "item_name": "item_name",
    "qty": "quantity",
    "uom": "unit_of_measure",
    "rate": "unit_price",
    "schedule_date": "delivery_date",
    "warehouse": "warehouse",
}

REQUISITION_LIST_FIELDS = [
    "name", "status", "owner", "cost_center", "creation",
    "schedule_date", "material_request_type",
]

# --- Purchase Order ---
PO_TO_CANONICAL = {
    "name": "order_id",
    "supplier": "supplier_id",
    "supplier_name": "supplier_name",
    "status": "status",
    "transaction_date": "order_date",
    "schedule_date": "delivery_date",
    "grand_total": "total_amount",
    "currency": "currency",
    "payment_terms_template": "payment_terms",
}

PO_ITEM_TO_CANONICAL = {
    "idx": "line_number",
    "item_code": "item_id",
    "item_name": "item_name",
    "qty": "quantity",
    "stock_uom": "unit_of_measure",
    "rate": "unit_price",
    "amount": "line_amount",
    "schedule_date": "delivery_date",
    "received_qty": "received_quantity",
    "billed_amt": "billed_amount",
    "material_request": "requisition_id",
    "warehouse": "warehouse",
}

PO_LIST_FIELDS = [
    "name", "supplier", "supplier_name", "status",
    "transaction_date", "schedule_date", "grand_total",
    "currency", "payment_terms_template", "per_received", "per_billed",
]

# --- Purchase Receipt (Goods Receipt) ---
RECEIPT_TO_CANONICAL = {
    "name": "receipt_id",
    "supplier": "supplier_id",
    "supplier_name": "supplier_name",
    "posting_date": "receipt_date",
    "status": "status",
}

RECEIPT_ITEM_TO_CANONICAL = {
    "idx": "line_number",
    "item_code": "item_id",
    "item_name": "item_name",
    "qty": "quantity_received",
    "stock_uom": "unit_of_measure",
    "rejected_qty": "rejected_quantity",
    "purchase_order": "order_id",
}

RECEIPT_LIST_FIELDS = [
    "name", "supplier", "supplier_name", "posting_date", "status",
]

# --- Purchase Invoice ---
INVOICE_TO_CANONICAL = {
    "name": "invoice_id",
    "supplier": "supplier_id",
    "supplier_name": "supplier_name",
    "bill_no": "vendor_invoice_number",
    "bill_date": "invoice_date",
    "due_date": "due_date",
    "posting_date": "posting_date",
    "grand_total": "total_amount",
    "outstanding_amount": "outstanding_amount",
    "currency": "currency",
    "payment_terms_template": "payment_terms",
    "status": "status",
}

INVOICE_ITEM_TO_CANONICAL = {
    "idx": "line_number",
    "item_code": "item_id",
    "item_name": "item_name",
    "qty": "quantity",
    "rate": "unit_price",
    "amount": "line_amount",
    "purchase_order": "order_id",
    "purchase_receipt": "receipt_id",
}

INVOICE_LIST_FIELDS = [
    "name", "supplier", "supplier_name", "bill_no", "bill_date",
    "due_date", "posting_date", "grand_total", "outstanding_amount",
    "currency", "status", "payment_terms_template",
]

# --- Payment Entry ---
PAYMENT_TO_CANONICAL = {
    "name": "payment_id",
    "payment_type": "payment_type",
    "party": "supplier_id",
    "party_name": "supplier_name",
    "paid_amount": "amount",
    "paid_to_account_currency": "currency",
    "posting_date": "payment_date",
    "mode_of_payment": "mode_of_payment",
    "reference_no": "reference_number",
    "status": "status",
}

PAYMENT_LIST_FIELDS = [
    "name", "payment_type", "party", "party_name",
    "paid_amount", "paid_to_account_currency", "posting_date",
    "mode_of_payment", "reference_no", "status",
]


def map_record(record: dict, field_map: dict) -> dict:
    """Map an ERPNext record to canonical format using a field mapping dict."""
    result = {}
    for erpnext_field, canonical_field in field_map.items():
        if erpnext_field in record:
            result[canonical_field] = record[erpnext_field]
    return result


def map_records(records: list[dict], field_map: dict) -> list[dict]:
    """Map a list of ERPNext records to canonical format."""
    return [map_record(r, field_map) for r in records]


def map_status_to_canonical(erpnext_status: str, doctype: str) -> str:
    """Normalize ERPNext status strings to canonical lowercase_underscore format."""
    status_maps = {
        "Material Request": {
            "Draft": "draft",
            "Pending": "pending_approval",
            "Partially Ordered": "approved",
            "Ordered": "ordered",
            "Transferred": "ordered",
            "Cancelled": "cancelled",
            "Stopped": "cancelled",
        },
        "Purchase Order": {
            "Draft": "draft",
            "To Receive and Bill": "to_receive",
            "To Bill": "to_bill",
            "To Receive": "to_receive",
            "Partially Received": "partially_received",
            "Completed": "completed",
            "Delivered": "received",
            "Cancelled": "cancelled",
            "Closed": "closed",
        },
        "Purchase Invoice": {
            "Draft": "draft",
            "Submitted": "submitted",
            "Unpaid": "unpaid",
            "Partly Paid": "partially_paid",
            "Paid": "paid",
            "Overdue": "overdue",
            "Cancelled": "cancelled",
            "Return": "return",
        },
        "Payment Entry": {
            "Draft": "draft",
            "Submitted": "submitted",
            "Cancelled": "cancelled",
        },
    }
    doctype_map = status_maps.get(doctype, {})
    return doctype_map.get(erpnext_status, erpnext_status.lower().replace(" ", "_"))
