# Adapters — Canonical ERP Interface

ERP-agnostic adapter layer. Translates canonical P2P operations to specific ERP REST APIs.

## Architecture

```
ERPAdapterBase (Abstract — 22 methods)
    │
    ├── ERPNextAdapter (Active — adapters/erpnext/)
    │   ├── ERPNextClient (HTTP client, 3 auth modes)
    │   ├── field_maps.py (Canonical ↔ ERPNext field names)
    │   └── oauth.py (Per-user API key management)
    │
    ├── SAPAdapter (Planned — BAPI / OData V4)
    ├── InforAdapter (Planned — ION API / M3)
    └── OracleAdapter (Planned — REST API / Procurement Cloud)
```

## Adding a New ERP

1. Implement `ERPAdapterBase` (all 22 abstract methods)
2. Add a field mapping module (your ERP field names → canonical names)
3. Add an HTTP client for your ERP's authentication
4. Set `ERP_TYPE=your_erp` in the Lambda environment
5. Update `canonical_api.py:_get_adapter()` to instantiate your adapter

## Key Files

| File | Description |
|------|-------------|
| `canonical_api.py` | FastAPI app — dual-mode Lambda handler (MCP + HTTP) |
| `erp_adapter_base.py` | Abstract interface — 22 methods covering the full P2P cycle |
| `models.py` | Pydantic models — canonical data types (Supplier, Item, Requisition, PO, Receipt, Invoice, Payment) |
| `erpnext/adapter.py` | ERPNext implementation of ERPAdapterBase |
| `erpnext/client.py` | ERPNext HTTP client (API key, session cookie, or password auth) |
| `erpnext/field_maps.py` | Bidirectional field name mapping |
| `erpnext/oauth.py` | ERPNextTokenManager — per-user credential management |

## Canonical Data Model

All adapters produce and consume these canonical types:

| Entity | Key Fields | ERP Operations |
|--------|-----------|----------------|
| `Supplier` | supplier_id, supplier_name, status | list, get |
| `Item` | item_id, item_name, standard_price | list, get |
| `Requisition` | requisition_id, status, line_items | list, get, create |
| `PurchaseOrder` | order_id, supplier_id, line_items | list, get, create |
| `Receipt` | receipt_id, order_id, line_items | list, get, create |
| `Invoice` | invoice_id, supplier_id, total_amount | list, get, create |
| `Payment` | payment_id, amount, invoice references | list, create |
| `SpendSummary` | total_spend, total_orders, overdue | get |
| `SupplierPerformance` | total_orders, total_spend, on_time_rate | get |
| `BudgetStatus` | budget_amount, actual_spend, utilization | get |
