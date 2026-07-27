// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { StatusBadge } from "@/components/ui/badge";
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table";
import { useTranslation } from "react-i18next";
import type { Invoice, PurchaseOrder, Receipt } from "@/types/p2p";

/** A document that may arrive either flat or wrapped in a `{ header }` envelope. */
type InvoiceDoc = Partial<Invoice> & { header?: Partial<Invoice> };
type PurchaseOrderDoc = Partial<PurchaseOrder> & { header?: Partial<PurchaseOrder> };
type ReceiptDoc = Partial<Receipt> & { header?: Partial<Receipt> };

interface MatchLine {
  // Component interface fields
  material?: string;
  description?: string;
  invoiceQty?: number;
  poQty?: number;
  grQty?: number;
  invoicePrice?: number;
  poPrice?: number;
  qtyMatch?: boolean;
  priceMatch?: boolean;
  // Agent response fields (snake_case)
  item?: string;
  item_name?: string;
  inv_qty?: number;
  po_qty?: number;
  gr_qty?: number;
  inv_price?: number;
  po_price?: number;
  qty_match?: boolean;
  price_match?: boolean;
  variance_pct?: number;
  status?: string;
}

/** Normalize a match line from either the component interface or agent response format. */
function normalizeLine(line: MatchLine) {
  return {
    material: line.material || line.item_name || line.item || "--",
    description: line.description || "",
    invoiceQty: line.invoiceQty ?? line.inv_qty ?? 0,
    poQty: line.poQty ?? line.po_qty ?? 0,
    grQty: line.grQty ?? line.gr_qty ?? 0,
    invoicePrice: line.invoicePrice ?? line.inv_price ?? 0,
    poPrice: line.poPrice ?? line.po_price ?? 0,
    qtyMatch: line.qtyMatch ?? line.qty_match ?? (line.status === "MATCH"),
    priceMatch: line.priceMatch ?? line.price_match ?? (line.status === "MATCH"),
  };
}

interface ThreeWayMatchProps {
  invoice: InvoiceDoc;
  purchaseOrder: PurchaseOrderDoc | null;
  goodsReceipt: ReceiptDoc | null;
  matchLines?: MatchLine[];
  overallResult?: string;
}

function DocSummaryCard({ title, fields }: {
  title: string;
  fields: { label: string; value: string | number }[];
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-sm font-semibold text-primary mb-3">{title}</div>
      <div className="space-y-2">
        {fields.map((f, i) => (
          <div key={i}>
            <div className="text-xs font-medium text-muted-foreground">{f.label}</div>
            <div className="text-sm">{f.value || "--"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MatchCell({ invoiceVal, compareVal, isPrice }: {
  invoiceVal: number;
  compareVal: number;
  isPrice?: boolean;
}) {
  const iv = invoiceVal ?? 0;
  const cv = compareVal ?? 0;
  const match = isPrice ? Math.abs(iv - cv) / (cv || 1) < 0.001 : Math.abs(iv - cv) < 0.01;
  const fmtOpts = isPrice
    ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
    : { minimumFractionDigits: 0, maximumFractionDigits: 0 };
  return (
    <span className={`inline-flex items-center gap-1 text-sm ${match ? "text-success" : "text-warning"}`}>
      {iv.toLocaleString(undefined, fmtOpts)}
      {!match && (
        <span className="text-xs text-warning">
          (expected {cv.toLocaleString(undefined, fmtOpts)})
        </span>
      )}
    </span>
  );
}

export default function ThreeWayMatch({ invoice, purchaseOrder, goodsReceipt, matchLines, overallResult }: ThreeWayMatchProps) {
  const { t } = useTranslation();
  const invHeader = invoice?.header || invoice || {};
  const poHeader = purchaseOrder?.header || purchaseOrder || {};
  const grHeader = goodsReceipt?.header || goodsReceipt || {};

  const fmt = (n: number | string | undefined | null) => {
    const num = parseFloat(String(n));
    // nosemgrep -- missing-template-string-indicator: literal string, no interpolation intended
    return isNaN(num) ? "--" : `$${num.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
  };

  return (
    <div className="space-y-6">
      {/* Overall match status */}
      {overallResult && (
        <div className="text-center py-2">
          <StatusBadge status={overallResult === "MATCHED" ? "success" : overallResult === "DISCREPANCY" ? "warning" : "error"}>
            {overallResult === "MATCHED" ? "3-Way Match: All documents align" :
             overallResult === "DISCREPANCY" ? "3-Way Match: Discrepancies found" :
             `3-Way Match: ${overallResult}`}
          </StatusBadge>
        </div>
      )}

      {/* Side-by-side document summaries */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <DocSummaryCard
          title="Invoice"
          fields={[
            { label: "Document", value: invHeader.invoice_id || "--" },
            { label: "Vendor Invoice", value: invHeader.vendor_invoice_number || "--" },
            { label: "Amount", value: fmt(invHeader.total_amount) },
            { label: "Date", value: invHeader.invoice_date || "--" },
            { label: "PO Reference", value: invHeader.order_id || "--" },
          ]}
        />
        <DocSummaryCard
          title="Purchase Order"
          fields={
            poHeader.order_id
              ? [
                  { label: "Document", value: poHeader.order_id },
                  { label: "Net Value", value: fmt(poHeader.total_amount) },
                  { label: "Date", value: poHeader.order_date || "--" },
                  { label: "Status", value: poHeader.status || "--" },
                ]
              : [{ label: "Status", value: "No PO data available" }]
          }
        />
        <DocSummaryCard
          title="Goods Receipt"
          fields={
            grHeader.receipt_id
              ? [
                  { label: "Document", value: grHeader.receipt_id },
                  { label: "Posting Date", value: grHeader.posting_date || "--" },
                  { label: "Receipt Date", value: grHeader.receipt_date || "--" },
                ]
              : [{ label: "Status", value: "No GR data available" }]
          }
        />
      </div>

      {/* Line-level comparison table */}
      {matchLines && matchLines.length > 0 && (
        <div>
          <h3 className="text-base font-semibold mb-3">{t("threeWayMatch.ui.lineItemComparison")}</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("threeWayMatch.ui.material")}</TableHead>
                <TableHead>{t("threeWayMatch.ui.invoiceQty")}</TableHead>
                <TableHead>{t("threeWayMatch.ui.poQty")}</TableHead>
                <TableHead>{t("threeWayMatch.ui.grQty")}</TableHead>
                <TableHead>{t("threeWayMatch.ui.invoicePrice")}</TableHead>
                <TableHead>{t("threeWayMatch.ui.poPrice")}</TableHead>
                <TableHead>{t("threeWayMatch.ui.lineStatus")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {matchLines.map(normalizeLine).map((item, i) => (
                <TableRow key={i}>
                  <TableCell className="font-medium">{item.description || item.material}</TableCell>
                  <TableCell><MatchCell invoiceVal={item.invoiceQty} compareVal={item.poQty} /></TableCell>
                  <TableCell>{Math.round(item.poQty).toLocaleString()}</TableCell>
                  <TableCell><MatchCell invoiceVal={item.grQty} compareVal={item.poQty} /></TableCell>
                  <TableCell><MatchCell invoiceVal={item.invoicePrice} compareVal={item.poPrice} isPrice /></TableCell>
                  <TableCell>{fmt(item.poPrice)}</TableCell>
                  <TableCell>
                    <StatusBadge status={item.qtyMatch && item.priceMatch ? "matched" : "warning"}>
                      {item.qtyMatch && item.priceMatch ? "Match" : "Discrepancy"}
                    </StatusBadge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
