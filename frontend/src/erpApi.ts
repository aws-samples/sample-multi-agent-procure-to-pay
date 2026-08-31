// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Canonical ERP API client.
 *
 * Calls the canonical adapter endpoints (/api/erp/*) which proxy to ERPNext.
 * Returns data with domain-standard field names (supplier_id, order_id, etc.).
 *
 * For agent invocations, use agentcore.ts instead.
 */

import { getToken, getAuthUser } from "./auth";
import type {
  SupplierList,
  Supplier,
  ItemList,
  Item,
  RequisitionList,
  Requisition,
  PurchaseOrderList,
  PurchaseOrder,
  ReceiptList,
  Receipt,
  InvoiceList,
  Invoice,
  PaymentList,
  SpendSummary,
  SupplierPerformanceList,
  BudgetStatusList,
} from "./types/p2p";

const API_BASE = import.meta.env.VITE_API_URL?.replace(/\/api\/?$/, "") || "";
const ERP_BASE = `${API_BASE}/api/erp`;

async function get<T>(path: string): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = { "Accept": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  // Only the local dev harness reads this header. Deployed, the adapter takes
  // identity from the JWT claims API Gateway verified and ignores the header.
  try {
    const user = await getAuthUser();
    if (user.email) headers["x-p2p-user-email"] = user.email;
  } catch { /* not logged in — proceed without */ }

  const res = await fetch(`${ERP_BASE}${path}`, { headers });
  if (res.status === 401) { window.location.href = "/"; throw new Error("Session expired"); }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`ERP API ${res.status}: ${text || res.statusText}`);
  }
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {
    "Accept": "application/json",
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  // Local dev harness only — see the note in get() above.
  try {
    const user = await getAuthUser();
    if (user.email) headers["x-p2p-user-email"] = user.email;
  } catch { /* not logged in */ }

  const res = await fetch(`${ERP_BASE}${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`ERP API ${res.status}: ${text || res.statusText}`);
  }
  return res.json();
}

export const erpApi = {
  // Suppliers
  listSuppliers: (group?: string) =>
    get<SupplierList>(`/suppliers${group ? `?group=${group}` : ""}`),
  getSupplier: (id: string) => get<Supplier>(`/suppliers/${encodeURIComponent(id)}`),

  // Items
  listItems: (group?: string, search?: string) => {
    const params = new URLSearchParams();
    if (group) params.set("group", group);
    if (search) params.set("search", search);
    const qs = params.toString();
    return get<ItemList>(`/items${qs ? `?${qs}` : ""}`);
  },
  getItem: (id: string) => get<Item>(`/items/${encodeURIComponent(id)}`),

  // Requisitions (Material Requests)
  listRequisitions: (status?: string) =>
    get<RequisitionList>(`/requisitions${status ? `?status=${status}` : ""}`),
  getRequisition: (id: string) =>
    get<Requisition>(`/requisitions/${encodeURIComponent(id)}`),

  // Purchase Orders
  listPurchaseOrders: (supplierId?: string, status?: string) => {
    const params = new URLSearchParams();
    if (supplierId) params.set("supplier_id", supplierId);
    if (status) params.set("status", status);
    const qs = params.toString();
    return get<PurchaseOrderList>(`/purchase-orders${qs ? `?${qs}` : ""}`);
  },
  getPurchaseOrder: (id: string) =>
    get<PurchaseOrder>(`/purchase-orders/${encodeURIComponent(id)}`),

  // Receipts (Goods Receipts)
  listReceipts: (orderId?: string) =>
    get<ReceiptList>(`/receipts${orderId ? `?order_id=${encodeURIComponent(orderId)}` : ""}`),
  getReceipt: (id: string) =>
    get<Receipt>(`/receipts/${encodeURIComponent(id)}`),

  // Invoices
  listInvoices: (supplierId?: string, status?: string) => {
    const params = new URLSearchParams();
    if (supplierId) params.set("supplier_id", supplierId);
    if (status) params.set("status", status);
    const qs = params.toString();
    return get<InvoiceList>(`/invoices${qs ? `?${qs}` : ""}`);
  },
  getInvoice: (id: string) =>
    get<Invoice>(`/invoices/${encodeURIComponent(id)}`),
  createInvoice: (data: {
    supplier_id: string;
    vendor_invoice_number?: string;
    invoice_date?: string;
    due_date?: string;
    order_id?: string;
    line_items: { line_number: number; item_id: string; quantity: number; unit_price: number; line_amount: number; order_id?: string }[];
  }) => post<Invoice>("/invoices", data),

  // Payments
  listPayments: () => get<PaymentList>("/payments"),

  // Analytics
  getSpendSummary: () => get<SpendSummary>("/analytics/spend-summary"),
  getSupplierPerformance: () =>
    get<SupplierPerformanceList>("/analytics/supplier-performance"),
  getBudgetStatus: () =>
    get<BudgetStatusList>("/analytics/budget-status"),
};
