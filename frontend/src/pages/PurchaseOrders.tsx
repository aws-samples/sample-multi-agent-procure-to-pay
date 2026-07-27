// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { erpApi } from "../erpApi";
import type { PurchaseOrder, PurchaseOrderLineItem } from "../types/p2p";
import { formatCurrency } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";

// PO status type mapping — StatusBadge auto-resolves from status string

export default function PurchaseOrders() {
  const { t } = useTranslation();
  const [items, setItems] = useState<PurchaseOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [selectedItem, setSelectedItem] = useState<PurchaseOrder | null>(null);
  const [showDetail, setShowDetail] = useState(false);

  useEffect(() => {
    erpApi.listPurchaseOrders().then((data) => {
      setItems(data.purchase_orders);
      setLoading(false);
    });
  }, []);

  const filtered = filterText
    ? items.filter((po) =>
        [po.order_id, po.supplier_name, po.supplier_id, po.status]
          .filter(Boolean)
          .some((v) => v!.toLowerCase().includes(filterText.toLowerCase()))
      )
    : items;

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("purchaseOrders.ui.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t("purchaseOrders.ui.subtitle", { total: filtered.length })}
        </p>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder={t("purchaseOrders.ui.searchPlaceholder")}
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Data Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">{t("purchaseOrders.ui.noPurchaseOrders")}</div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("purchaseOrders.ui.colPoNumber")}</TableHead>
                <TableHead>{t("purchaseOrders.ui.colSupplier")}</TableHead>
                <TableHead>{t("purchaseOrders.ui.colStatus")}</TableHead>
                <TableHead>{t("purchaseOrders.ui.colOrderDate")}</TableHead>
                <TableHead className="text-right">{t("purchaseOrders.ui.colTotalAmount")}</TableHead>
                <TableHead>{t("purchaseOrders.ui.colPaymentTerms")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((po) => (
                <TableRow
                  key={po.order_id}
                  className={cn(
                    "cursor-pointer",
                    selectedItem?.order_id === po.order_id && "bg-muted",
                  )}
                  onClick={() => {
                    setSelectedItem(po);
                    setShowDetail(true);
                  }}
                >
                  <TableCell className="font-medium">{po.order_id}</TableCell>
                  <TableCell>{po.supplier_name || po.supplier_id}</TableCell>
                  <TableCell><StatusBadge status={po.status || "unknown"} /></TableCell>
                  <TableCell>{po.order_date || "\u2014"}</TableCell>
                  <TableCell className="text-right font-mono">{formatCurrency(po.total_amount)}</TableCell>
                  <TableCell>{po.payment_terms || "\u2014"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Detail Modal */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>{t("purchaseOrders.ui.poLabel")} {selectedItem?.order_id}</DialogTitle>
          </DialogHeader>
          {selectedItem && (
            <div className="space-y-5">
              {/* Summary grid */}
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("purchaseOrders.ui.colSupplier")}</p>
                  <p className="text-sm">{selectedItem.supplier_name || selectedItem.supplier_id}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("purchaseOrders.ui.colStatus")}</p>
                  <StatusBadge status={selectedItem.status || "unknown"} />
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("purchaseOrders.ui.colTotalAmount")}</p>
                  <p className="text-sm font-mono">{formatCurrency(selectedItem.total_amount)}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("purchaseOrders.ui.colOrderDate")}</p>
                  <p className="text-sm">{selectedItem.order_date || "\u2014"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("purchaseOrders.ui.colPaymentTerms")}</p>
                  <p className="text-sm">{selectedItem.payment_terms || "\u2014"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("purchaseOrders.ui.deliveryDate")}</p>
                  <p className="text-sm">{selectedItem.delivery_date || "\u2014"}</p>
                </div>
              </div>

              {/* Line Items */}
              {selectedItem.line_items && selectedItem.line_items.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                    {t("purchaseOrders.ui.lineItems", { total: selectedItem.line_items.length })}
                  </p>
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("purchaseOrders.ui.colLine")}</TableHead>
                          <TableHead>{t("purchaseOrders.ui.colItemId")}</TableHead>
                          <TableHead>{t("purchaseOrders.ui.colItemName")}</TableHead>
                          <TableHead className="text-right">{t("purchaseOrders.ui.colQty")}</TableHead>
                          <TableHead className="text-right">{t("purchaseOrders.ui.colUnitPrice")}</TableHead>
                          <TableHead className="text-right">{t("purchaseOrders.ui.colAmount")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {selectedItem.line_items.map((li: PurchaseOrderLineItem, idx: number) => (
                          <TableRow key={idx}>
                            <TableCell>{li.line_number}</TableCell>
                            <TableCell>{li.item_id}</TableCell>
                            <TableCell>{li.item_name || "\u2014"}</TableCell>
                            <TableCell className="text-right">{li.quantity}</TableCell>
                            <TableCell className="text-right font-mono">{formatCurrency(li.unit_price)}</TableCell>
                            <TableCell className="text-right font-mono">{formatCurrency(li.line_amount)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
