// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import AgentStepList from "@/components/AgentProgress";
import { erpApi } from "../erpApi";
import type { Invoice, PaymentAnalysis } from "../types/p2p";
import { useAgentStream } from "../hooks/useAgentStream";
import { formatCurrency, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { useTranslation } from "react-i18next";

/** Payment agent result — analysis fields are optional until the run completes. */
type PaymentResult = Partial<PaymentAnalysis> & { error?: string };

export default function Payments() {
  const { t } = useTranslation();
  const [items, setItems] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [selectedItem, setSelectedItem] = useState<Invoice | null>(null);
  const [showModal, setShowModal] = useState(false);

  const agent = useAgentStream();

  // Derive display state directly from the agent stream — no mirroring effect.
  const analyzing = agent.isRunning;
  const agentResult: PaymentResult | null = agent.error
    ? { error: agent.error }
    : (agent.result as PaymentResult | null);

  useEffect(() => {
    erpApi.listInvoices().then((data) => {
      // Show invoices that have an outstanding amount (need payment)
      const payable = data.invoices.filter((i) => {
        const status = i.status;
        return status === "unpaid" || status === "overdue" || status === "partially_paid" ||
               (i.outstanding_amount != null && i.outstanding_amount > 0);
      });
      setItems(payable);
      setLoading(false);
    });
  }, []);

  const analyzePayment = async () => {
    if (!selectedItem) return;
    setShowModal(true);
    agent.reset();
    try {
      await agent.invoke("payment", selectedItem.invoice_id, {
        order_id: selectedItem.order_id || "",
      });
    } catch { /* error surfaced via agent.error */ }
  };

  const filtered = filterText
    ? items.filter((i) =>
        [i.invoice_id, i.supplier_name, i.supplier_id, i.order_id]
          .filter(Boolean)
          .some((v) => v!.toLowerCase().includes(filterText.toLowerCase()))
      )
    : items;

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("payments.ui.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t("payments.ui.subtitle", { total: filtered.length })}
        </p>
      </div>

      {/* Toolbar: search + agent action */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t("payments.ui.searchPlaceholder")}
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            className="pl-9"
          />
        </div>
        {selectedItem && (
          <Button size="sm" disabled={!selectedItem} onClick={analyzePayment} loading={analyzing}>
            {t("payments.ui.analyzePayment")}
          </Button>
        )}
      </div>

      {/* Data Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">{t("payments.ui.noInvoices")}</div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("payments.ui.colInvoice")}</TableHead>
                <TableHead>{t("payments.ui.colSupplier")}</TableHead>
                <TableHead className="text-right">{t("payments.ui.colTotalAmount")}</TableHead>
                <TableHead>{t("payments.ui.colPaymentTerms")}</TableHead>
                <TableHead>{t("payments.ui.colDueDate")}</TableHead>
                <TableHead>{t("payments.ui.colStatus")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <TableRow
                  key={item.invoice_id}
                  className={cn(
                    "cursor-pointer",
                    selectedItem?.invoice_id === item.invoice_id && "bg-muted",
                  )}
                  onClick={() => setSelectedItem(selectedItem?.invoice_id === item.invoice_id ? null : item)}
                >
                  <TableCell className="font-medium">{item.invoice_id}</TableCell>
                  <TableCell>{item.supplier_name || item.supplier_id}</TableCell>
                  <TableCell className="text-right font-mono">{formatCurrency(item.total_amount)}</TableCell>
                  <TableCell>{item.payment_terms || "--"}</TableCell>
                  <TableCell>{item.due_date || "--"}</TableCell>
                  <TableCell><StatusBadge status={item.status || "unknown"} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Payment Agent Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>{t("payments.ui.agentTitle")}</DialogTitle>
          </DialogHeader>

          {analyzing ? (
            <div className="py-4">
              <AgentStepList progress={agent.progress} isRunning={analyzing} title="Payment Agent" />
            </div>
          ) : agentResult ? (
            <div className="space-y-5">
              {/* Recommendation */}
              <div>
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("payments.ui.paymentRecommendation")}</p>
                <StatusBadge
                  status={
                    agentResult.payment_recommendation === "PAY_AT_DISCOUNT" ? "approved"
                    : agentResult.payment_recommendation === "PAY_NOW" ? "approved"
                    : "submitted"
                  }
                >
                  {agentResult.payment_recommendation}
                </StatusBadge>
              </div>

              {/* Payment Details */}
              {agentResult.payment_details && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("payments.ui.paymentDetails")}</p>
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 rounded-lg border p-4">
                    <div>
                      <p className="text-xs text-muted-foreground">{t("payments.ui.invoiceAmount")}</p>
                      <p className="text-sm font-mono font-medium">{formatCurrency(agentResult.payment_details.invoice_amount)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("payments.ui.discountAvailable")}</p>
                      <p className="text-sm font-medium">
                        {agentResult.payment_details.discount_available
                          ? `Yes -- ${agentResult.payment_details.discount_percent}%`
                          : "No"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("payments.ui.discountAmount")}</p>
                      <p className="text-sm font-mono font-medium">{formatCurrency(agentResult.payment_details.discount_amount)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("payments.ui.dueDate")}</p>
                      <p className="text-sm font-medium">{agentResult.payment_details.due_date}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("payments.ui.recommendedPayDate")}</p>
                      <p className="text-sm font-medium">{agentResult.payment_details.recommended_pay_date}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("payments.ui.netPayment")}</p>
                      <p className="text-sm font-mono font-medium">{formatCurrency(agentResult.payment_details.net_payment_amount)}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Annualized Discount Rate */}
              {(agentResult.annualized_discount_rate ?? 0) > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("payments.ui.annualizedDiscountRate")}</p>
                  <p className="text-2xl font-bold">{agentResult.annualized_discount_rate}%</p>
                </div>
              )}

              {/* Reasoning */}
              {agentResult.reasoning && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("payments.ui.reasoning")}</p>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{agentResult.reasoning}</p>
                </div>
              )}

              {/* Flags */}
              {agentResult.flags && agentResult.flags.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("payments.ui.flags")}</p>
                  <div className="space-y-1.5">
                    {agentResult.flags.map((f: string, i: number) => (
                      <p key={i} className="text-sm text-muted-foreground">! {f}</p>
                    ))}
                  </div>
                </div>
              )}

              {/* Error */}
              {agentResult.error && (
                <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
                  {agentResult.error}
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
