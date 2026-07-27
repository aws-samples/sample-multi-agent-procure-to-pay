// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Canonical P2P types — domain-standard naming.
 * Maps to the canonical adapter API (ERPNext backend).
 */

// --- Supplier ---

export interface Supplier {
  supplier_id: string;
  supplier_name: string;
  supplier_group?: string;
  country?: string;
  city?: string;
  region?: string;
  default_currency?: string;
  payment_terms?: string;
  tax_id?: string;
  status?: string;
  website?: string;
  primary_contact_name?: string;
  primary_contact_email?: string;
  primary_contact_phone?: string;
}

export interface SupplierList {
  suppliers: Supplier[];
  total_count: number;
}

// --- Item ---

export interface Item {
  item_id: string;
  item_name: string;
  item_group?: string;
  unit_of_measure?: string;
  standard_price?: number;
  currency?: string;
  description?: string;
  is_stock_item?: boolean;
}

export interface ItemList {
  items: Item[];
  total_count: number;
}

// --- Requisition (Material Request) ---

export interface RequisitionLineItem {
  line_number: number;
  item_id: string;
  item_name?: string;
  quantity: number;
  unit_of_measure?: string;
  unit_price?: number;
  currency?: string;
  delivery_date?: string;
  preferred_supplier_id?: string;
  warehouse?: string;
}

export interface Requisition {
  requisition_id: string;
  status?: string;
  requester?: string;
  department?: string;
  created_date?: string;
  required_date?: string;
  total_amount?: number;
  currency?: string;
  purpose?: string;
  line_items: RequisitionLineItem[];
}

export interface RequisitionList {
  requisitions: Requisition[];
  total_count: number;
}

// --- Purchase Order ---

export interface PurchaseOrderLineItem {
  line_number: number;
  item_id: string;
  item_name?: string;
  quantity: number;
  unit_of_measure?: string;
  unit_price: number;
  line_amount: number;
  delivery_date?: string;
  received_quantity?: number;
  billed_amount?: number;
  requisition_id?: string;
  warehouse?: string;
}

export interface PurchaseOrder {
  order_id: string;
  supplier_id: string;
  supplier_name?: string;
  status?: string;
  order_date?: string;
  delivery_date?: string;
  total_amount?: number;
  currency?: string;
  payment_terms?: string;
  requisition_id?: string;
  line_items: PurchaseOrderLineItem[];
}

export interface PurchaseOrderList {
  purchase_orders: PurchaseOrder[];
  total_count: number;
}

// --- Receipt (Goods Receipt) ---

export interface ReceiptLineItem {
  line_number: number;
  item_id: string;
  item_name?: string;
  quantity_received: number;
  unit_of_measure?: string;
  rejected_quantity?: number;
  order_id?: string;
}

export interface Receipt {
  receipt_id: string;
  order_id?: string;
  supplier_id?: string;
  supplier_name?: string;
  receipt_date?: string;
  posting_date?: string;
  status?: string;
  line_items: ReceiptLineItem[];
}

export interface ReceiptList {
  receipts: Receipt[];
  total_count: number;
}

// --- Invoice ---

export interface InvoiceLineItem {
  line_number: number;
  item_id: string;
  item_name?: string;
  quantity: number;
  unit_price: number;
  line_amount: number;
  order_id?: string;
  receipt_id?: string;
}

export interface Invoice {
  invoice_id: string;
  supplier_id: string;
  supplier_name?: string;
  vendor_invoice_number?: string;
  invoice_date?: string;
  due_date?: string;
  posting_date?: string;
  total_amount?: number;
  outstanding_amount?: number;
  currency?: string;
  payment_terms?: string;
  status?: string;
  order_id?: string;
  line_items: InvoiceLineItem[];
}

export interface InvoiceList {
  invoices: Invoice[];
  total_count: number;
}

// --- Payment ---

export interface Payment {
  payment_id: string;
  payment_type?: string;
  supplier_id?: string;
  supplier_name?: string;
  amount: number;
  currency?: string;
  payment_date?: string;
  mode_of_payment?: string;
  reference_number?: string;
  status?: string;
  invoices?: string[];
}

export interface PaymentList {
  payments: Payment[];
  total_count: number;
}

// --- Analytics ---

export interface SpendSummary {
  total_spend: number;
  total_orders: number;
  total_invoices: number;
  total_suppliers: number;
  open_orders: number;
  unpaid_invoices: number;
  overdue_invoices: number;
  currency?: string;
}

export interface SupplierPerformance {
  supplier_id: string;
  supplier_name: string;
  total_orders: number;
  total_spend: number;
  on_time_delivery_rate?: number;
  quality_score?: number;
  currency?: string;
}

export interface SupplierPerformanceList {
  suppliers: SupplierPerformance[];
  total_count: number;
}

// --- Budget ---

export interface BudgetStatus {
  cost_center: string;
  cost_center_name: string;
  fiscal_year: string;
  budget_amount: number;
  actual_spend: number;
  remaining: number;
  utilization_pct: number;
  exceeded: boolean;
  currency?: string;
}

export interface BudgetStatusList {
  budgets: BudgetStatus[];
  total_count: number;
}

// --- Agent Results ---

export interface AgentFinding {
  check: string;
  status: "PASS" | "WARN" | "FAIL";
  detail: string;
}

export interface RequisitionAnalysis {
  recommendation: "APPROVE" | "REJECT" | "ESCALATE";
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  confidence: number;
  reasoning: string;
  findings: AgentFinding[];
  auto_approved: boolean;
  estimated_savings_opportunity?: number;
}

export interface InvoiceMatchResult {
  match_result: "MATCHED" | "DISCREPANCY" | "ESCALATE";
  three_way_match: boolean;
  confidence: number;
  reasoning: string;
  discrepancies: string[];
  line_matches: any[];
  auto_approved?: boolean;
}

export interface PaymentAnalysis {
  payment_recommendation: string;
  confidence: number;
  reasoning: string;
  payment_details: {
    invoice_amount: number;
    discount_available: boolean;
    discount_percent: number;
    discount_amount: number;
    due_date: string;
    recommended_pay_date: string;
    net_payment_amount: number;
  };
  annualized_discount_rate?: number;
  flags: string[];
}
