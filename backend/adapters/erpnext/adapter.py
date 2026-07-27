# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
ERPNext implementation of ERPAdapterBase.

Translates canonical P2P operations to ERPNext REST API calls.
"""

import io
import logging
from typing import Optional

from adapters.erp_adapter_base import ERPAdapterBase
from adapters.models import (
    Supplier, SupplierList,
    Item, ItemList,
    Requisition, RequisitionCreate, RequisitionList, RequisitionLineItem,
    PurchaseOrder, PurchaseOrderCreate, PurchaseOrderList, PurchaseOrderLineItem,
    Receipt, ReceiptCreate, ReceiptList, ReceiptLineItem,
    Invoice, InvoiceCreate, InvoiceList, InvoiceLineItem,
    Payment, PaymentCreate, PaymentList,
    SpendSummary, SupplierPerformanceList, SupplierPerformance,
    BudgetStatus, BudgetStatusList,
)
from adapters.erpnext.client import ERPNextClient
from adapters.erpnext.field_maps import (
    map_record, map_records, map_status_to_canonical,
    SUPPLIER_TO_CANONICAL, SUPPLIER_LIST_FIELDS,
    ITEM_TO_CANONICAL, ITEM_LIST_FIELDS,
    REQUISITION_TO_CANONICAL, REQUISITION_ITEM_TO_CANONICAL, REQUISITION_LIST_FIELDS,
    PO_TO_CANONICAL, PO_ITEM_TO_CANONICAL, PO_LIST_FIELDS,
    RECEIPT_TO_CANONICAL, RECEIPT_ITEM_TO_CANONICAL, RECEIPT_LIST_FIELDS,
    INVOICE_TO_CANONICAL, INVOICE_ITEM_TO_CANONICAL, INVOICE_LIST_FIELDS,
    PAYMENT_TO_CANONICAL, PAYMENT_LIST_FIELDS,
)

logger = logging.getLogger("p2p.adapters.erpnext")

DEFAULT_WAREHOUSE = "Stores - AMG"
DEFAULT_COMPANY = "Apex Manufacturing Group"
DEFAULT_COST_CENTER = "Main - AMG"
DEFAULT_DEPARTMENT = "Operations - AMG"


class ERPNextAdapter(ERPAdapterBase):
    """ERPNext P2P adapter."""

    def __init__(self, client: ERPNextClient):
        self.client = client

    # --- Suppliers ---

    def list_suppliers(self, status: Optional[str] = None,
                       group: Optional[str] = None) -> SupplierList:
        filters = []
        if group:
            filters.append(["supplier_group", "=", group])
        records = self.client.get_list("Supplier", fields=SUPPLIER_LIST_FIELDS,
                                       filters=filters or None)
        suppliers = [Supplier(**map_record(r, SUPPLIER_TO_CANONICAL)) for r in records]
        return SupplierList(suppliers=suppliers, total_count=len(suppliers))

    def get_supplier(self, supplier_id: str) -> Supplier:
        record = self.client.get("Supplier", supplier_id)
        mapped = map_record(record, SUPPLIER_TO_CANONICAL)
        # Get default payment terms
        if record.get("payment_terms"):
            mapped["payment_terms"] = record["payment_terms"]
        # Get primary contact info if available
        if record.get("supplier_primary_contact"):
            mapped["primary_contact_name"] = record.get("supplier_primary_contact")
        return Supplier(**mapped)

    # --- Items ---

    def list_items(self, group: Optional[str] = None,
                   search: Optional[str] = None) -> ItemList:
        filters = []
        or_filters = []
        if group:
            filters.append(["item_group", "=", group])
        if search:
            # Split multi-word searches into individual keyword matches (OR)
            # "hex bolts" → matches items containing "hex" OR "bolts"
            words = [w.strip() for w in search.split() if w.strip()]
            if len(words) == 1:
                filters.append(["item_name", "like", f"%{words[0]}%"])
            else:
                for word in words:
                    or_filters.append(["item_name", "like", f"%{word}%"])
        records = self.client.get_list("Item", fields=ITEM_LIST_FIELDS,
                                       filters=filters or None,
                                       or_filters=or_filters or None)
        items = [Item(**map_record(r, ITEM_TO_CANONICAL)) for r in records]
        return ItemList(items=items, total_count=len(items))

    def get_item(self, item_id: str) -> Item:
        record = self.client.get("Item", item_id)
        return Item(**map_record(record, ITEM_TO_CANONICAL))

    # --- Requisitions (Material Requests) ---

    def list_requisitions(self, status: Optional[str] = None,
                          requester: Optional[str] = None,
                          detail: bool = True) -> RequisitionList:
        filters = [["material_request_type", "=", "Purchase"]]
        if status:
            filters.append(["status", "=", status.replace("_", " ").title()])
        if requester:
            filters.append(["owner", "=", requester])
        records = self.client.get_list("Material Request",
                                       fields=REQUISITION_LIST_FIELDS,
                                       filters=filters,
                                       order_by="creation desc")
        if detail:
            # Enrich each requisition with line items and totals from detail endpoint
            reqs = []
            for r in records:
                try:
                    reqs.append(self.get_requisition(r["name"]))
                except Exception:
                    mapped = map_record(r, REQUISITION_TO_CANONICAL)
                    mapped["status"] = map_status_to_canonical(r.get("status", ""), "Material Request")
                    reqs.append(Requisition(**mapped))
        else:
            # Fast path — basic fields only, no N+1 detail fetches
            reqs = []
            for r in records:
                mapped = map_record(r, REQUISITION_TO_CANONICAL)
                mapped["status"] = map_status_to_canonical(r.get("status", ""), "Material Request")
                reqs.append(Requisition(**mapped))
        return RequisitionList(requisitions=reqs, total_count=len(reqs))

    def get_requisition(self, requisition_id: str) -> Requisition:
        record = self.client.get("Material Request", requisition_id)
        mapped = map_record(record, REQUISITION_TO_CANONICAL)
        mapped["status"] = map_status_to_canonical(record.get("status", ""), "Material Request")
        # Map line items
        items = []
        for item in record.get("items", []):
            line = map_record(item, REQUISITION_ITEM_TO_CANONICAL)
            items.append(RequisitionLineItem(**line))
        mapped["line_items"] = items
        # Calculate total from items if not available
        if not mapped.get("total_amount"):
            mapped["total_amount"] = sum(
                (li.unit_price or 0) * li.quantity for li in items
            )
        return Requisition(**mapped)

    def create_requisition(self, data: RequisitionCreate) -> Requisition:
        from datetime import date, timedelta
        default_date = (date.today() + timedelta(days=14)).isoformat()
        schedule = data.required_date or default_date
        # ERPNext rejects schedule_date before today
        if schedule < date.today().isoformat():
            schedule = default_date

        items = []
        for li in data.line_items:
            item = {
                "item_code": li.item_id,
                "qty": li.quantity,
                "schedule_date": schedule,
                "warehouse": li.warehouse or DEFAULT_WAREHOUSE,
            }
            if li.unit_price:
                item["rate"] = li.unit_price
            items.append(item)

        mr_data = {
            "material_request_type": "Purchase",
            "schedule_date": schedule,
            "company": DEFAULT_COMPANY,
            "cost_center": data.cost_center or DEFAULT_COST_CENTER,
            "department": data.department or DEFAULT_DEPARTMENT,
            "items": items,
        }

        doc = self.client.insert("Material Request", mr_data)
        if doc and doc.get("name"):
            self.client.submit("Material Request", doc["name"])
            return self.get_requisition(doc["name"])
        raise ValueError("Failed to create requisition in ERPNext")

    def stop_requisition(self, requisition_id: str):
        """Stop a Material Request (marks as rejected/stopped in ERPNext)."""
        try:
            resp = self.client.session.post(
                f"{self.client.base_url}/api/method/frappe.client.set_value",
                json={
                    "doctype": "Material Request",
                    "name": requisition_id,
                    "fieldname": "status",
                    "value": "Stopped",
                },
            )
            if resp.ok:
                logger.info(f"Stopped MR {requisition_id}")
            else:
                logger.warning(f"Failed to stop MR {requisition_id}: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Failed to stop MR {requisition_id}: {e}")

    # --- Purchase Orders ---

    def list_purchase_orders(self, supplier_id: Optional[str] = None,
                             status: Optional[str] = None) -> PurchaseOrderList:
        # Map canonical status back to ERPNext status(es) for filtering
        CANONICAL_TO_ERPNEXT_PO = {
            "to_receive": ["To Receive and Bill", "To Receive"],
            "to_bill": ["To Bill"],
            "partially_received": ["Partially Received"],
            "completed": ["Completed"],
            "received": ["Delivered"],
            "draft": ["Draft"],
            "cancelled": ["Cancelled", "Closed"],
        }
        filters = []
        if supplier_id:
            filters.append(["supplier", "=", supplier_id])
        if status:
            erp_statuses = CANONICAL_TO_ERPNEXT_PO.get(status)
            if erp_statuses:
                filters.append(["status", "in", erp_statuses])
            else:
                filters.append(["status", "=", status.replace("_", " ").title()])
        records = self.client.get_list("Purchase Order", fields=PO_LIST_FIELDS,
                                       filters=filters or None,
                                       order_by="transaction_date desc")
        orders = []
        for r in records:
            mapped = map_record(r, PO_TO_CANONICAL)
            mapped["status"] = map_status_to_canonical(r.get("status", ""), "Purchase Order")
            # Enrich with line items from detail
            try:
                detail = self.client.get("Purchase Order", r["name"])
                items = [PurchaseOrderLineItem(**map_record(item, PO_ITEM_TO_CANONICAL))
                         for item in detail.get("items", [])]
                mapped["line_items"] = items
            except Exception:
                mapped["line_items"] = []
            orders.append(PurchaseOrder(**mapped))
        return PurchaseOrderList(purchase_orders=orders, total_count=len(orders))

    def get_purchase_order(self, order_id: str) -> PurchaseOrder:
        record = self.client.get("Purchase Order", order_id)
        mapped = map_record(record, PO_TO_CANONICAL)
        mapped["status"] = map_status_to_canonical(record.get("status", ""), "Purchase Order")
        items = []
        for item in record.get("items", []):
            line = map_record(item, PO_ITEM_TO_CANONICAL)
            items.append(PurchaseOrderLineItem(**line))
        mapped["line_items"] = items
        return PurchaseOrder(**mapped)

    def create_purchase_order(self, data: PurchaseOrderCreate) -> PurchaseOrder:
        from datetime import date, timedelta
        default_date = (date.today() + timedelta(days=14)).isoformat()

        # Build MR item name lookup if we have a requisition link
        # ERPNext needs material_request_item (row name) for proper MR→PO linkage
        mr_item_map = {}  # item_code → MR item row name
        mr_ids = set(li.requisition_id for li in data.line_items if li.requisition_id)
        for mr_id in mr_ids:
            try:
                mr = self.client.get("Material Request", mr_id)
                for mr_item in mr.get("items", []):
                    mr_item_map[mr_item.get("item_code", "")] = mr_item.get("name", "")
            except Exception as e:
                logger.warning(f"Could not fetch MR {mr_id} for item linkage: {e}")

        items = []
        for li in data.line_items:
            item = {
                "item_code": li.item_id,
                "qty": li.quantity,
                "rate": li.unit_price,
                "schedule_date": data.delivery_date or li.delivery_date or default_date,
                "warehouse": li.warehouse or DEFAULT_WAREHOUSE,
            }
            if li.requisition_id:
                item["material_request"] = li.requisition_id
                # Add the MR item row name for proper ERPNext linkage
                if li.item_id in mr_item_map:
                    item["material_request_item"] = mr_item_map[li.item_id]
            items.append(item)

        # Map common payment term abbreviations to ERPNext template names
        PAYMENT_TERMS_MAP = {
            "NT15": "Net 15", "NT30": "Net 30", "NT45": "Net 45", "NT60": "Net 60",
            "N30": "Net 30", "N45": "Net 45", "N60": "Net 60",
            "2/10N30": "2/10 Net 30", "2/10NT30": "2/10 Net 30",
            "1/15N45": "1/15 Net 45", "1/15NT45": "1/15 Net 45",
        }
        resolved_terms = PAYMENT_TERMS_MAP.get(
            (data.payment_terms or "").replace(" ", ""),
            data.payment_terms
        ) if data.payment_terms else None

        po_data = {
            "supplier": data.supplier_id,
            "transaction_date": data.delivery_date or default_date,
            "schedule_date": data.delivery_date or default_date,
            "company": DEFAULT_COMPANY,
            "items": items,
        }
        if resolved_terms:
            po_data["payment_terms_template"] = resolved_terms

        doc = self.client.insert("Purchase Order", po_data)
        if doc and doc.get("name"):
            self.client.submit("Purchase Order", doc["name"])
            # Update linked Material Requests to "Ordered" status
            # ERPNext requires material_request_item for auto-update, which we
            # may not have. Manually set the MR per_ordered to trigger status change.
            mr_ids = set()
            for li in data.line_items:
                if li.requisition_id:
                    mr_ids.add(li.requisition_id)
            for mr_id in mr_ids:
                try:
                    self._update_mr_ordered_status(mr_id)
                except Exception as e:
                    logger.warning(f"Failed to update MR {mr_id} status: {e}")
            return self.get_purchase_order(doc["name"])
        raise ValueError("Failed to create purchase order in ERPNext")

    def _update_mr_ordered_status(self, mr_id: str):
        """Update Material Request to reflect it has been ordered.

        ERPNext auto-calculates status from per_ordered on items. We need to
        set ordered_qty on each MR item to match qty, then save to trigger
        the status recalculation to "Ordered".
        """
        base = self.client.base_url
        session = self.client.session

        # Get the MR with items to find item row names
        try:
            mr = self.client.get("Material Request", mr_id)
        except Exception as e:
            logger.warning(f"Could not fetch MR {mr_id}: {e}")
            return

        # Update each item's ordered_qty to match qty (marks as fully ordered)
        items_update = []
        for item in mr.get("items", []):
            items_update.append({
                "name": item.get("name"),
                "ordered_qty": item.get("qty", 0),
            })

        try:
            resp = session.put(
                f"{base}/api/resource/Material Request/{mr_id}",
                json={"items": items_update, "per_ordered": 100},
            )
            if resp.ok:
                logger.info(f"Updated MR {mr_id} items ordered_qty — status should recalculate to Ordered")
            else:
                logger.warning(f"PUT update for MR {mr_id} returned {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            logger.warning(f"PUT update failed for MR {mr_id}: {e}")

        # Fallback: use frappe.db.set_value to force status (bypasses validation)
        try:
            resp = session.post(
                f"{base}/api/method/frappe.client.set_value",
                json={
                    "doctype": "Material Request",
                    "name": mr_id,
                    "fieldname": "per_ordered",
                    "value": 100,
                },
            )
            logger.info(f"Set per_ordered=100 for MR {mr_id}: {resp.status_code}")
        except Exception as e:
            logger.warning(f"set_value per_ordered failed for MR {mr_id}: {e}")

    # --- Receipts (Purchase Receipts) ---

    def list_receipts(self, order_id: Optional[str] = None) -> ReceiptList:
        filters: list = [["docstatus", "!=", 2]]  # exclude cancelled
        if order_id:
            # Frappe child table filter: ["ChildDoctype", "field", "=", "value"]
            filters.append(["Purchase Receipt Item", "purchase_order", "=", order_id])
        records = self.client.get_list("Purchase Receipt", fields=RECEIPT_LIST_FIELDS,
                                       filters=filters or None,
                                       order_by="posting_date desc")
        # Deduplicate: child table filters return one row per matching item
        seen = set()
        unique_records = []
        for r in records:
            if r["name"] not in seen:
                seen.add(r["name"])
                unique_records.append(r)
        records = unique_records
        # Enrich with PO reference and item count from detail (PO ref is on items, not header)
        receipts = []
        for r in records:
            mapped = map_record(r, RECEIPT_TO_CANONICAL)
            try:
                detail = self.client.get("Purchase Receipt", r["name"])
                items = detail.get("items", [])
                mapped["line_items"] = [ReceiptLineItem(**map_record(item, RECEIPT_ITEM_TO_CANONICAL)) for item in items]
                # Set order_id from first item's purchase_order
                if items and not mapped.get("order_id"):
                    mapped["order_id"] = items[0].get("purchase_order", "")
            except Exception:
                mapped["line_items"] = []
            receipts.append(Receipt(**mapped))
        return ReceiptList(receipts=receipts, total_count=len(receipts))

    def get_receipt(self, receipt_id: str) -> Receipt:
        record = self.client.get("Purchase Receipt", receipt_id)
        mapped = map_record(record, RECEIPT_TO_CANONICAL)
        items = []
        for item in record.get("items", []):
            line = map_record(item, RECEIPT_ITEM_TO_CANONICAL)
            items.append(ReceiptLineItem(**line))
        mapped["line_items"] = items
        return Receipt(**mapped)

    def create_receipt(self, data: ReceiptCreate) -> Receipt:
        # Fetch PO items to get ERPNext row names and rates
        # Required for ERPNext to auto-update PO received quantities
        po_item_map: dict[str, dict] = {}  # item_code → {name, rate}
        if data.order_id:
            try:
                po_doc = self.client.get("Purchase Order", data.order_id)
                for po_item in po_doc.get("items", []):
                    po_item_map[po_item.get("item_code", "")] = {
                        "name": po_item.get("name", ""),
                        "rate": po_item.get("rate", 0),
                    }
            except Exception as e:
                logger.warning("Failed to fetch PO %s for item linkage: %s", data.order_id, e)

        items = []
        for li in data.line_items:
            item = {
                "item_code": li.item_id,
                "qty": li.quantity_received,
                "warehouse": DEFAULT_WAREHOUSE,
                "purchase_order": data.order_id,
            }
            # Link to specific PO item row and set rate for proper tracking
            po_info = po_item_map.get(li.item_id, {})
            if po_info.get("name"):
                item["purchase_order_item"] = po_info["name"]
            if po_info.get("rate"):
                item["rate"] = po_info["rate"]
            if li.rejected_quantity:
                item["rejected_qty"] = li.rejected_quantity
            items.append(item)

        doc = self.client.insert("Purchase Receipt", {
            "supplier": data.supplier_id,
            "company": DEFAULT_COMPANY,
            "items": items,
        })
        if doc and doc.get("name"):
            self.client.submit("Purchase Receipt", doc["name"])
            return self.get_receipt(doc["name"])
        raise ValueError("Failed to create receipt in ERPNext")

    # --- Invoices (Purchase Invoices) ---

    def list_invoices(self, supplier_id: Optional[str] = None,
                      status: Optional[str] = None) -> InvoiceList:
        filters: list = [["docstatus", "!=", 2]]  # exclude cancelled
        if supplier_id:
            filters.append(["supplier", "=", supplier_id])
        if status:
            filters.append(["status", "=", status.replace("_", " ").title()])
        records = self.client.get_list("Purchase Invoice", fields=INVOICE_LIST_FIELDS,
                                       filters=filters or None,
                                       order_by="posting_date desc")
        # Enrich with PO reference and items (PO ref is on items, not header)
        invoices = []
        for r in records:
            mapped = map_record(r, INVOICE_TO_CANONICAL)
            mapped["status"] = map_status_to_canonical(r.get("status", ""), "Purchase Invoice")
            try:
                detail = self.client.get("Purchase Invoice", r["name"])
                items = detail.get("items", [])
                mapped["line_items"] = [InvoiceLineItem(**map_record(item, INVOICE_ITEM_TO_CANONICAL)) for item in items]
                if items and not mapped.get("order_id"):
                    mapped["order_id"] = items[0].get("purchase_order", "")
            except Exception:
                mapped["line_items"] = []
            invoices.append(Invoice(**mapped))
        return InvoiceList(invoices=invoices, total_count=len(invoices))

    def get_invoice(self, invoice_id: str) -> Invoice:
        record = self.client.get("Purchase Invoice", invoice_id)
        mapped = map_record(record, INVOICE_TO_CANONICAL)
        mapped["status"] = map_status_to_canonical(record.get("status", ""), "Purchase Invoice")
        items = []
        for item in record.get("items", []):
            line = map_record(item, INVOICE_ITEM_TO_CANONICAL)
            items.append(InvoiceLineItem(**line))
        mapped["line_items"] = items
        return Invoice(**mapped)

    def create_invoice(self, data: InvoiceCreate) -> Invoice:
        # Fetch PO items for row name linkage (purchase_order_item)
        # Required for ERPNext to auto-update PO billed quantities
        po_item_map: dict[str, str] = {}  # item_code → PO row name
        po_id = data.order_id or (data.line_items[0].order_id if data.line_items else "")
        if po_id:
            try:
                po_doc = self.client.get("Purchase Order", po_id)
                for po_item in po_doc.get("items", []):
                    po_item_map[po_item.get("item_code", "")] = po_item.get("name", "")
            except Exception as e:
                logger.warning("Failed to fetch PO %s for invoice linkage: %s", po_id, e)

        items = []
        for li in data.line_items:
            item = {
                "item_code": li.item_id,
                "qty": li.quantity,
                "rate": li.unit_price,
            }
            if li.order_id:
                item["purchase_order"] = li.order_id
                # Link to specific PO item row for proper billed qty tracking
                if li.item_id in po_item_map:
                    item["po_detail"] = po_item_map[li.item_id]
            if li.receipt_id:
                item["purchase_receipt"] = li.receipt_id
            items.append(item)

        doc = self.client.insert("Purchase Invoice", {
            "supplier": data.supplier_id,
            "bill_no": data.vendor_invoice_number,
            "bill_date": data.invoice_date,
            "due_date": data.due_date,
            "company": DEFAULT_COMPANY,
            "items": items,
        })
        if doc and doc.get("name"):
            self.client.submit("Purchase Invoice", doc["name"])
            return self.get_invoice(doc["name"])
        raise ValueError("Failed to create invoice in ERPNext")

    # --- Payments ---

    def list_payments(self) -> PaymentList:
        records = self.client.get_list(
            "Payment Entry",
            fields=PAYMENT_LIST_FIELDS,
            filters=[["payment_type", "=", "Pay"]],
            order_by="posting_date desc",
        )
        payments = []
        for r in records:
            mapped = map_record(r, PAYMENT_TO_CANONICAL)
            mapped["status"] = map_status_to_canonical(r.get("status", ""), "Payment Entry")
            payments.append(Payment(**mapped))
        return PaymentList(payments=payments, total_count=len(payments))

    def create_payment(self, data: PaymentCreate) -> Payment:
        doc_data = {
            "payment_type": "Pay",
            "party_type": "Supplier",
            "party": data.supplier_id,
            "paid_amount": data.amount,
            "received_amount": data.amount,
            "source_exchange_rate": 1.0,
            "target_exchange_rate": 1.0,
            "paid_from": "Cash - AMG",
            "paid_to": "Creditors - AMG",
            "mode_of_payment": data.mode_of_payment or "Wire Transfer",
            "company": DEFAULT_COMPANY,
        }
        if data.invoice_id:
            # Fetch invoice to get the full outstanding for allocation
            invoice_outstanding = data.amount
            try:
                inv = self.client.get("Purchase Invoice", data.invoice_id)
                invoice_outstanding = float(inv.get("outstanding_amount", 0) or inv.get("grand_total", 0) or data.amount)
            except Exception:
                pass  # nosec B110 -- fall back to caller-supplied amount if fetch fails

            # Allocate the full outstanding amount against the invoice
            doc_data["references"] = [{
                "reference_doctype": "Purchase Invoice",
                "reference_name": data.invoice_id,
                "allocated_amount": invoice_outstanding,
            }]

            # If paying less than outstanding (e.g., early payment discount),
            # add deductions to balance the entry.
            # ERPNext Pay type formula: difference = paid - allocated - deductions
            # So deduction must be NEGATIVE to balance: paid - allocated - (-discount) = 0
            if data.deductions:
                doc_data["deductions"] = [
                    {
                        "account": d.account if hasattr(d, 'account') else d.get("account", "Write Off - AMG"),
                        "cost_center": d.cost_center if hasattr(d, 'cost_center') else d.get("cost_center", "Main - AMG"),
                        "amount": -(abs(d.amount if hasattr(d, 'amount') else d.get("amount", 0))),
                    }
                    for d in data.deductions
                ]
            elif data.amount < invoice_outstanding:
                # Fallback: auto-create deduction for the difference
                discount = round(invoice_outstanding - data.amount, 2)
                doc_data["deductions"] = [{
                    "account": "Write Off - AMG",
                    "cost_center": "Main - AMG",
                    "amount": -discount,
                }]

        doc = self.client.insert("Payment Entry", doc_data)
        if doc and doc.get("name"):
            try:
                self.client.submit("Payment Entry", doc["name"])
            except Exception as e:
                logger.warning(f"Payment created but submit failed: {e}")
            record = self.client.get("Payment Entry", doc["name"])
            mapped = map_record(record, PAYMENT_TO_CANONICAL)
            mapped["status"] = map_status_to_canonical(record.get("status", ""), "Payment Entry")
            return Payment(**mapped)
        raise ValueError("Failed to create payment in ERPNext")

    # --- Analytics ---

    def get_spend_summary(self) -> SpendSummary:
        total_orders = self.client.get_count("Purchase Order", [["docstatus", "=", 1]])
        total_invoices = self.client.get_count("Purchase Invoice", [["docstatus", "=", 1]])
        total_suppliers = self.client.get_count("Supplier")
        open_orders = self.client.get_count("Purchase Order", [
            ["docstatus", "=", 1],
            ["status", "not in", ["Completed", "Cancelled", "Closed"]],
        ])
        unpaid_invoices = self.client.get_count("Purchase Invoice", [
            ["docstatus", "=", 1],
            ["outstanding_amount", ">", 0],
        ])
        from datetime import date
        today_str = date.today().isoformat()
        overdue_invoices = self.client.get_count("Purchase Invoice", [
            ["docstatus", "=", 1],
            ["outstanding_amount", ">", 0],
            ["due_date", "<", today_str],
        ])

        # Sum total spend from submitted POs
        pos = self.client.get_list("Purchase Order",
                                   fields=["sum(grand_total) as total"],
                                   filters=[["docstatus", "=", 1]])
        total_spend = float(pos[0].get("total", 0) or 0) if pos else 0.0

        return SpendSummary(
            total_spend=total_spend,
            total_orders=total_orders,
            total_invoices=total_invoices,
            total_suppliers=total_suppliers,
            open_orders=open_orders,
            unpaid_invoices=unpaid_invoices,
            overdue_invoices=overdue_invoices,
        )

    def get_supplier_performance(self) -> SupplierPerformanceList:
        # Get PO totals grouped by supplier
        pos = self.client.get_list(
            "Purchase Order",
            fields=["supplier", "supplier_name",
                     "count(name) as order_count",
                     "sum(grand_total) as total_spend"],
            filters=[["docstatus", "=", 1]],
            group_by="supplier",
            order_by="total_spend desc",
        )
        perfs = []
        for r in pos:
            sid = r.get("supplier") or ""
            sname = r.get("supplier_name") or ""
            if not sid:
                continue  # skip records with null supplier
            perfs.append(SupplierPerformance(
                supplier_id=sid,
                supplier_name=sname or sid,
                total_orders=int(r.get("order_count", 0) or 0),
                total_spend=float(r.get("total_spend", 0) or 0),
            ))
        return SupplierPerformanceList(suppliers=perfs, total_count=len(perfs))

    # --- Budgets ---

    def get_budget_status(self, cost_center: Optional[str] = None) -> BudgetStatusList:
        from datetime import date
        fiscal_year = str(date.today().year)

        filters = [["fiscal_year", "=", fiscal_year], ["docstatus", "=", 1]]
        if cost_center:
            filters.append(["cost_center", "like", f"%{cost_center}%"])

        budgets_raw = self.client.get_list(
            "Budget",
            fields=["name", "cost_center", "fiscal_year"],
            filters=filters,
        )

        results = []
        for b in budgets_raw:
            # Get budget detail with accounts (budget amounts)
            try:
                detail = self.client.get("Budget", b["name"])
            except Exception:
                continue  # nosec B112 -- skip budgets we can't fetch; surface the rest

            budget_amount = 0.0
            for acct in detail.get("accounts", []):
                budget_amount += float(acct.get("budget_amount", 0) or 0)

            cc = detail.get("cost_center", "")
            cc_name = cc.split(" - ")[0] if " - " in cc else cc

            # Get actual spend from submitted POs against this cost center
            pos = self.client.get_list(
                "Purchase Order",
                fields=["sum(grand_total) as total"],
                filters=[
                    ["docstatus", "=", 1],
                    ["cost_center", "=", cc],
                ],
            )
            actual_spend = float(pos[0].get("total", 0) or 0) if pos else 0.0

            remaining = budget_amount - actual_spend
            utilization = round((actual_spend / budget_amount) * 100, 1) if budget_amount > 0 else 0.0

            results.append(BudgetStatus(
                cost_center=cc,
                cost_center_name=cc_name,
                fiscal_year=fiscal_year,
                budget_amount=budget_amount,
                actual_spend=actual_spend,
                remaining=remaining,
                utilization_pct=utilization,
                exceeded=remaining < 0,
            ))

        return BudgetStatusList(budgets=results, total_count=len(results))

    # --- Cost Centers ---

    def list_payment_terms(self) -> list[dict]:
        records = self.client.get_list(
            "Payment Terms Template",
            fields=["name"],
            limit=0,
        )
        return [{"name": r["name"]} for r in records]

    def list_cost_centers(self) -> "CostCenterList":
        from adapters.models import CostCenter, CostCenterList
        records = self.client.get_list(
            "Cost Center",
            fields=["name", "cost_center_name", "parent_cost_center", "is_group"],
            filters=[["is_group", "=", 0], ["company", "=", DEFAULT_COMPANY]],
        )
        centers = [CostCenter(
            cost_center_id=r["name"],
            cost_center_name=r.get("cost_center_name", r["name"].split(" - ")[0]),
            parent=r.get("parent_cost_center", ""),
        ) for r in records]
        return CostCenterList(cost_centers=centers, total_count=len(centers))

    # --- File Attachments ---

    def attach_file(self, docname: str, doctype: str, file_bytes: bytes, filename: str) -> dict:
        """Attach a file to an ERPNext document using the Frappe upload_file API."""
        url = f"{self.client.base_url}/api/method/upload_file"
        files = {"file": (filename, io.BytesIO(file_bytes), "application/pdf")}
        data = {
            "doctype": doctype,
            "docname": docname,
            "is_private": 1,
        }
        resp = self.client.session.post(url, files=files, data=data)
        resp.raise_for_status()
        result = resp.json().get("message", {})
        logger.info("Attached %s to %s %s: %s", filename, doctype, docname, result.get("file_url", ""))
        return {"file_url": result.get("file_url", ""), "file_name": result.get("file_name", "")}
