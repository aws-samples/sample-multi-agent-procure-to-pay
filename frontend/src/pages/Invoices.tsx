// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Search, Loader2, AlertTriangle, Upload, ChevronDown, ChevronRight as ChevronRightIcon, Package, DollarSign, CheckCircle2, Circle } from "lucide-react";
import AgentStepList from "@/components/AgentProgress";
import { erpApi } from "../erpApi";
import { api } from "../api";
import type { Invoice, PurchaseOrder } from "../types/p2p";
import { useAgentStream } from "../hooks/useAgentStream";
import { formatCurrency, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";

interface POInvoiceGroup {
  po: PurchaseOrder;
  invoices: Invoice[];
}

export default function Invoices() {
  const { t } = useTranslation();
  const [allItems, setAllItems] = useState<Invoice[]>([]);
  const [poMap, setPoMap] = useState<Record<string, PurchaseOrder>>({});
  const [loading, setLoading] = useState(true);
  const [selectedItem, setSelectedItem] = useState<Invoice | null>(null);
  const [matchResult, setMatchResult] = useState<any>(null);
  const [_matchMeta, setMatchMeta] = useState<any>(null);
  const [matchPO, setMatchPO] = useState<any>(null);
  const [matchGR, setMatchGR] = useState<any>(null);
  const [paymentResult, setPaymentResult] = useState<any>(null);
  const [runningPayment, setRunningPayment] = useState(false);
  const [matching, setMatching] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [activeTab, setActiveTab] = useState("needs_review");
  const [filterText, setFilterText] = useState("");
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [extractionResult, setExtractionResult] = useState<any>(null);
  const [createdInvoice, setCreatedInvoice] = useState<any>(null);
  const [expandedPOs, setExpandedPOs] = useState<Set<string>>(new Set());
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [schedulingPayment, setSchedulingPayment] = useState(false);
  const [paymentCreated, setPaymentCreated] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const matchAgent = useAgentStream();
  const paymentAgent = useAgentStream();

  useEffect(() => {
    Promise.all([erpApi.listInvoices(), erpApi.listPurchaseOrders()]).then(
      ([invoiceData, poData]) => {
        setAllItems(invoiceData.invoices);
        const map: Record<string, PurchaseOrder> = {};
        for (const po of poData.purchase_orders) map[po.order_id] = po;
        setPoMap(map);
        const poIds = new Set(invoiceData.invoices.map((i: Invoice) => i.order_id).filter(Boolean) as string[]);
        setExpandedPOs(poIds);
        setLoading(false);
      },
    );
  }, []);

  // Categorize
  const needsReview = allItems.filter((i) => !i.status || i.status === "draft" || i.status === "unpaid");
  const overdue = allItems.filter((i) => i.status === "overdue");
  const paid = allItems.filter((i) => i.status === "paid");
  const partlyPaid = allItems.filter((i) => i.status === "partially_paid");

  const getTabItems = () => {
    switch (activeTab) {
      case "needs_review": return [...needsReview, ...overdue];
      case "paid": return paid;
      case "partly_paid": return partlyPaid;
      case "all": return allItems;
      default: return allItems;
    }
  };

  // Group by PO
  const tabItems = getTabItems();
  const filteredItems = filterText
    ? tabItems.filter((i) =>
        [i.invoice_id, i.supplier_name, i.supplier_id, i.vendor_invoice_number, i.order_id]
          .filter(Boolean)
          .some((v) => v!.toLowerCase().includes(filterText.toLowerCase()))
      )
    : tabItems;

  const invoicesByPO: Record<string, Invoice[]> = {};
  const orphanInvoices: Invoice[] = [];
  for (const inv of filteredItems) {
    if (inv.order_id) {
      if (!invoicesByPO[inv.order_id]) invoicesByPO[inv.order_id] = [];
      invoicesByPO[inv.order_id].push(inv);
    } else {
      orphanInvoices.push(inv);
    }
  }
  const poGroups: POInvoiceGroup[] = Object.entries(invoicesByPO).map(([poId, invoices]) => ({
    po: poMap[poId] || { order_id: poId, supplier_id: "", status: "unknown", line_items: [] } as PurchaseOrder,
    invoices,
  }));
  poGroups.sort((a, b) => (b.po.order_date || "").localeCompare(a.po.order_date || ""));

  const queueCount = needsReview.length + overdue.length;
  const isActionable = selectedItem && selectedItem.status !== "paid" && selectedItem.status !== "cancelled";
  const showMatchButton = (activeTab === "needs_review" || activeTab === "all") && isActionable;

  /* ---------- 3-Way Match ---------- */
  const matchSelected = async () => {
    if (!selectedItem) return;
    setMatching(true);
    setShowModal(true);
    setMatchResult(null);
    setMatchMeta(null);
    setMatchPO(null);
    setMatchGR(null);
    setPaymentResult(null);
    setRunningPayment(false);
    matchAgent.reset();
    paymentAgent.reset();
    try {
      await matchAgent.invoke("invoice_matching", selectedItem.invoice_id, {
        order_id: selectedItem.order_id || "",
      });
    } catch { /* in agent.error */ }
  };

  const prevMatchResult = useRef<any>(null);
  useEffect(() => {
    if (matchAgent.result && matchAgent.result !== prevMatchResult.current) {
      prevMatchResult.current = matchAgent.result;
      const result = matchAgent.result;
      setMatchResult(result);
      setMatchMeta(matchAgent.meta);
      setMatching(false);

      const poRef = selectedItem?.order_id || result.order_id;
      if (poRef) {
        (async () => {
          try {
            const [poData, grData] = await Promise.all([
              erpApi.getPurchaseOrder(poRef),
              erpApi.listReceipts(poRef),
            ]);
            if (poData) setMatchPO(poData);
            if (grData.receipts.length > 0) setMatchGR(grData.receipts[0]);
          } catch { /* non-critical */ }
        })();
      }

      // Auto-chain to payment agent if matched
      if (result.auto_approved || result.match_result === "MATCHED") {
        _runPaymentAgent();
      }
    }
    if (matchAgent.error && matching) {
      setMatchResult({ error: matchAgent.error });
      setMatching(false);
    }
  }, [matchAgent.result, matchAgent.error]);

  /* ---------- Payment Agent (chained after match OR standalone) ---------- */
  const _runPaymentAgent = async () => {
    if (!selectedItem) return;
    setRunningPayment(true);
    paymentAgent.reset();
    try {
      await paymentAgent.invoke("payment", selectedItem.invoice_id, {
        order_id: selectedItem.order_id || "",
      });
    } catch { /* in paymentAgent.error */ }
  };

  /* ---------- Standalone Analyze Payment ---------- */
  const analyzePaymentSelected = async () => {
    if (!selectedItem) return;
    setShowPaymentModal(true);
    setPaymentResult(null);
    setRunningPayment(true);
    paymentAgent.reset();
    try {
      await paymentAgent.invoke("payment", selectedItem.invoice_id, {
        order_id: selectedItem.order_id || "",
      });
    } catch { /* in paymentAgent.error */ }
  };

  /* ---------- Schedule Payment Workflow ---------- */
  const schedulePaymentWorkflow = async () => {
    if (!selectedItem) return;
    setShowScheduleModal(true);
    setMatchResult(null);
    setPaymentResult(null);
    setPaymentCreated(null);
    setSchedulingPayment(false);
    setRunningPayment(false);
    // Step 1: Run 3-way match first
    setMatching(true);
    matchAgent.reset();
    paymentAgent.reset();
    try {
      await matchAgent.invoke("invoice_matching", selectedItem.invoice_id, {
        order_id: selectedItem.order_id || "",
      });
    } catch { /* error */ }
    // Payment agent auto-chains via useEffect when match completes
  };

  const confirmSchedulePayment = async () => {
    if (!selectedItem || !paymentResult) return;
    setSchedulingPayment(true);
    try {
      const invoiceAmount = selectedItem.outstanding_amount || selectedItem.total_amount || 0;
      const netAmount = paymentResult.payment_details?.net_payment_amount || invoiceAmount;
      const discountAmount = paymentResult.payment_details?.discount_amount || 0;
      const isDiscount = paymentResult.payment_recommendation === "PAY_AT_DISCOUNT" && discountAmount > 0;

      const result = await api.schedulePayment({
        invoice_id: selectedItem.invoice_id,
        supplier_id: selectedItem.supplier_id || selectedItem.supplier_name || "",
        amount: isDiscount ? netAmount : invoiceAmount,
        order_id: selectedItem.order_id || "",
        mode_of_payment: "Wire Transfer",
        deductions: isDiscount ? [{ account: "Write Off - AMG", cost_center: "Main - AMG", amount: discountAmount }] : [],
        match_result: matchResult || {},
        payment_analysis: paymentResult || {},
      });
      setPaymentCreated(result);
      // Refresh invoice list
      Promise.all([erpApi.listInvoices(), erpApi.listPurchaseOrders()]).then(([invData, poData]) => {
        setAllItems(invData.invoices);
        const map: Record<string, PurchaseOrder> = {};
        for (const po of poData.purchase_orders) map[po.order_id] = po;
        setPoMap(map);
      });
    } catch (err: any) {
      setPaymentCreated({ error: err.message || "Payment failed" });
    }
    setSchedulingPayment(false);
  };

  const prevPayResult = useRef<any>(null);
  useEffect(() => {
    if (paymentAgent.result && paymentAgent.result !== prevPayResult.current) {
      prevPayResult.current = paymentAgent.result;
      setPaymentResult(paymentAgent.result);
      setRunningPayment(false);
    }
    if (paymentAgent.error && runningPayment) {
      setPaymentResult({ error: paymentAgent.error });
      setRunningPayment(false);
    }
  }, [paymentAgent.result, paymentAgent.error]);

  const togglePO = (poId: string) => {
    setExpandedPOs((prev) => {
      const next = new Set(prev);
      if (next.has(poId)) next.delete(poId);
      else next.add(poId);
      return next;
    });
  };

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("invoices.ui.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("invoices.ui.subtitle")}
          </p>
        </div>
        <div className="flex gap-2">
          {showMatchButton && (
            <>
              <Button variant="outline" size="sm" disabled={!selectedItem} onClick={matchSelected} loading={matching}>
                {t("invoices.ui.threeWayMatch")}
              </Button>
              <Button variant="outline" size="sm" disabled={!selectedItem} onClick={analyzePaymentSelected}>
                {t("invoices.ui.analyzePayment")}
              </Button>
              <Button size="sm" disabled={!selectedItem} onClick={schedulePaymentWorkflow}>
                {t("invoices.ui.schedulePayment")}
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
            <Upload className="h-4 w-4 mr-1" /> {t("invoices.ui.uploadInvoice")}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setUploading(true);
              setExtractionResult(null);
              setCreatedInvoice(null);
              setShowUploadModal(true);
              try {
                const { job_id } = await api.analyzeAndCreateInvoice(file);
                const poll = async () => {
                  for (let i = 0; i < 30; i++) {
                    await new Promise((r) => setTimeout(r, 3000));
                    try {
                      const status = await api.getInvoiceJobStatus(job_id);
                      if (status.step) setExtractionResult((prev: any) => ({ ...prev, _step: status.step }));
                      if (status.status === "completed") {
                        setExtractionResult(status.extraction);
                        if (status.invoice) {
                          setCreatedInvoice(status.invoice);
                          Promise.all([erpApi.listInvoices(), erpApi.listPurchaseOrders()]).then(
                            ([invData, poData]) => {
                              setAllItems(invData.invoices);
                              const map: Record<string, PurchaseOrder> = {};
                              for (const po of poData.purchase_orders) map[po.order_id] = po;
                              setPoMap(map);
                            }
                          );
                        }
                        setUploading(false);
                        return;
                      }
                      if (status.status === "failed") {
                        setExtractionResult({ error: status.error || "Processing failed" });
                        setUploading(false);
                        return;
                      }
                    } catch { /* retry */ }
                  }
                  setExtractionResult({ error: "Timed out" });
                  setUploading(false);
                };
                poll();
              } catch (err: any) {
                setExtractionResult({ error: err.message || "Failed" });
                setUploading(false);
              }
              if (fileInputRef.current) fileInputRef.current.value = "";
            }}
          />
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={(v) => { setActiveTab(v); setSelectedItem(null); }}>
        <TabsList>
          <TabsTrigger value="needs_review">{t("invoices.ui.reviewQueueTab", { count: queueCount })}</TabsTrigger>
          <TabsTrigger value="partly_paid">{t("invoices.ui.partlyPaidTab", { count: partlyPaid.length })}</TabsTrigger>
          <TabsTrigger value="paid">{t("invoices.ui.paidTab", { count: paid.length })}</TabsTrigger>
          <TabsTrigger value="all">{t("invoices.ui.allTab", { count: allItems.length })}</TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} forceMount className="mt-4 space-y-4">
          <div className="relative max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input placeholder={t("invoices.ui.searchPlaceholder")} value={filterText}
              onChange={(e) => setFilterText(e.target.value)} className="pl-9" />
          </div>

          {/* Grouped Table */}
          {loading ? (
            <div className="flex items-center justify-center py-12"><Spinner size="lg" /></div>
          ) : poGroups.length === 0 && orphanInvoices.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">{t("invoices.ui.noInvoicesFound")}</div>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8"></TableHead>
                    <TableHead>{t("invoices.ui.document")}</TableHead>
                    <TableHead>{t("invoices.ui.supplier")}</TableHead>
                    <TableHead>{t("invoices.ui.status")}</TableHead>
                    <TableHead className="text-right">{t("invoices.ui.amount")}</TableHead>
                    <TableHead className="text-right">{t("invoices.ui.outstanding")}</TableHead>
                    <TableHead>{t("invoices.ui.invoiceDate")}</TableHead>
                    <TableHead>{t("invoices.ui.dueDate")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {poGroups.map((group) => {
                    const isExpanded = expandedPOs.has(group.po.order_id);
                    return (
                      <React.Fragment key={group.po.order_id}>
                        {/* PO Header */}
                        <TableRow className="cursor-pointer bg-muted/30 hover:bg-muted/50" onClick={() => togglePO(group.po.order_id)}>
                          <TableCell>
                            <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                              {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRightIcon className="h-4 w-4" />}
                            </Button>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Package className="h-4 w-4 text-blue-500" />
                              <span className="font-semibold text-sm">{group.po.order_id}</span>
                              <span className="text-xs text-muted-foreground">({group.invoices.length} inv)</span>
                            </div>
                          </TableCell>
                          <TableCell className="font-medium">{group.po.supplier_name || "\u2014"}</TableCell>
                          <TableCell><StatusBadge status={group.po.status || "unknown"} /></TableCell>
                          <TableCell className="text-right font-medium">{group.po.total_amount != null ? formatCurrency(group.po.total_amount) : "\u2014"}</TableCell>
                          <TableCell></TableCell>
                          <TableCell>{group.po.order_date || "\u2014"}</TableCell>
                          <TableCell></TableCell>
                        </TableRow>

                        {/* Invoice rows */}
                        {isExpanded && group.invoices.map((inv) => (
                          <TableRow
                            key={inv.invoice_id}
                            className={cn("cursor-pointer", selectedItem?.invoice_id === inv.invoice_id ? "bg-primary/10" : "bg-card")}
                            onClick={() => setSelectedItem(selectedItem?.invoice_id === inv.invoice_id ? null : inv)}
                          >
                            <TableCell>
                              <span className="inline-block w-4 ml-2 border-l border-b border-muted-foreground/30 h-3" />
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                <DollarSign className="h-3.5 w-3.5 text-green-500" />
                                <span className="font-mono text-xs text-primary">{inv.invoice_id}</span>
                                {inv.vendor_invoice_number && (
                                  <span className="text-xs text-muted-foreground">({inv.vendor_invoice_number})</span>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground">{inv.supplier_name || "\u2014"}</TableCell>
                            <TableCell><StatusBadge status={inv.status || "unknown"} /></TableCell>
                            <TableCell className="text-right font-mono text-sm">{formatCurrency(inv.total_amount)}</TableCell>
                            <TableCell className="text-right font-mono text-sm">{formatCurrency(inv.outstanding_amount)}</TableCell>
                            <TableCell className="text-sm">{inv.invoice_date || "\u2014"}</TableCell>
                            <TableCell className="text-sm">{inv.due_date || "\u2014"}</TableCell>
                          </TableRow>
                        ))}
                      </React.Fragment>
                    );
                  })}
                  {/* Orphan invoices */}
                  {orphanInvoices.map((inv) => (
                    <TableRow key={inv.invoice_id} className={cn("cursor-pointer", selectedItem?.invoice_id === inv.invoice_id && "bg-muted")}
                      onClick={() => setSelectedItem(selectedItem?.invoice_id === inv.invoice_id ? null : inv)}>
                      <TableCell></TableCell>
                      <TableCell className="font-mono text-xs">{inv.invoice_id}</TableCell>
                      <TableCell>{inv.supplier_name || "\u2014"}</TableCell>
                      <TableCell><StatusBadge status={inv.status || "unknown"} /></TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(inv.total_amount)}</TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(inv.outstanding_amount)}</TableCell>
                      <TableCell>{inv.invoice_date || "\u2014"}</TableCell>
                      <TableCell>{inv.due_date || "\u2014"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* 3-Way Match + Payment Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>{t("invoices.ui.invoiceMatchingAgent")}</DialogTitle>
          </DialogHeader>

          {matching ? (
            <div className="py-4">
              <AgentStepList progress={matchAgent.progress} isRunning={matching} title={t("invoices.ui.invoiceMatchingAgent")} />
            </div>
          ) : matchResult ? (
            <div className="space-y-5">
              {/* Match Result */}
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("invoices.ui.matchResult")}</p>
                  <StatusBadge status={matchResult.match_result === "MATCHED" ? "matched" : matchResult.match_result === "DISCREPANCY" ? "warning" : "error"}>
                    {matchResult.match_result}
                  </StatusBadge>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("invoices.ui.threeWayMatchLabel")}</p>
                  <span className="text-sm font-medium">{matchResult.three_way_match ? t("invoices.ui.yes") : t("invoices.ui.no")}</span>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("invoices.ui.confidence")}</p>
                  <span className="text-sm font-medium">{((matchResult.confidence || 0) * 100).toFixed(0)}%</span>
                </div>
              </div>

              {/* 3-Way Comparison Cards */}
              {matchPO && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border p-3 space-y-1">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("invoices.ui.purchaseOrder")}</p>
                    <p className="text-sm font-medium">{matchPO.order_id}</p>
                    <p className="text-sm font-mono">{formatCurrency(matchPO.total_amount)}</p>
                    <p className="text-xs text-muted-foreground">{matchPO.supplier_name}</p>
                  </div>
                  {selectedItem && (
                    <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("invoices.ui.invoice")}</p>
                      <p className="text-sm font-medium">{selectedItem.invoice_id}</p>
                      <p className="text-sm font-mono">{formatCurrency(selectedItem.total_amount)}</p>
                      <p className="text-xs text-muted-foreground">{selectedItem.supplier_name}</p>
                    </div>
                  )}
                  {matchGR ? (
                    <div className="rounded-lg border p-3 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("invoices.ui.goodsReceipt")}</p>
                      <p className="text-sm font-medium">{matchGR.receipt_id}</p>
                      <p className="text-sm">{matchGR.line_items?.length || 0} items received</p>
                      <p className="text-xs text-muted-foreground">{matchGR.receipt_date || "--"}</p>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed p-3 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{t("invoices.ui.goodsReceipt")}</p>
                      <p className="text-sm text-muted-foreground">{t("invoices.ui.noReceiptFound")}</p>
                    </div>
                  )}
                </div>
              )}

              {/* Line Matches */}
              {matchResult.line_matches?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("invoices.ui.lineMatches")}</p>
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("invoices.ui.item")}</TableHead>
                          <TableHead className="text-right">{t("invoices.ui.poQty")}</TableHead>
                          <TableHead className="text-right">{t("invoices.ui.invoiceQty")}</TableHead>
                          <TableHead className="text-right">{t("invoices.ui.grQty")}</TableHead>
                          <TableHead>{t("invoices.ui.status")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {matchResult.line_matches.map((lm: any, i: number) => (
                          <TableRow key={i}>
                            <TableCell className="font-medium text-sm">{lm.item_name || lm.item_id || lm.material || `Line ${i + 1}`}</TableCell>
                            <TableCell className="text-right">{lm.po_qty ?? "--"}</TableCell>
                            <TableCell className="text-right">{lm.inv_qty ?? lm.invoice_qty ?? "--"}</TableCell>
                            <TableCell className="text-right">{lm.gr_qty ?? "--"}</TableCell>
                            <TableCell>
                              <StatusBadge status={lm.status === "MATCH" || lm.status === "MATCHED" ? "matched" : "warning"}>
                                {lm.status || "--"}
                              </StatusBadge>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}

              {/* Reasoning */}
              {matchResult.reasoning && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("invoices.ui.matchReasoning")}</p>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{matchResult.reasoning}</p>
                </div>
              )}

              {/* Discrepancies */}
              {matchResult.discrepancies?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("invoices.ui.discrepancies")}</p>
                  {matchResult.discrepancies.map((d: string, i: number) => (
                    <div key={i} className="flex items-start gap-2 text-sm">
                      <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" /><span>{d}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Payment Agent Results (chained after match) */}
              {(runningPayment || paymentResult) && (
                <div className="border-t pt-4">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">{t("invoices.ui.paymentAnalysis")}</p>
                  {runningPayment ? (
                    <AgentStepList progress={paymentAgent.progress} isRunning={runningPayment} title={t("invoices.ui.paymentAgent")} />
                  ) : paymentResult?.error ? (
                    <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
                      {paymentResult.error}
                    </div>
                  ) : paymentResult ? (
                    <div className="space-y-3">
                      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                        <div>
                          <p className="text-xs text-muted-foreground">{t("invoices.ui.recommendation")}</p>
                          <StatusBadge status={
                            paymentResult.payment_recommendation === "PAY_AT_DISCOUNT" || paymentResult.payment_recommendation === "PAY_NOW" ? "approved" : "warning"
                          }>
                            {(paymentResult.payment_recommendation || "").replace(/_/g, " ")}
                          </StatusBadge>
                        </div>
                        {paymentResult.payment_details?.discount_available && (
                          <>
                            <div>
                              <p className="text-xs text-muted-foreground">{t("invoices.ui.discount")}</p>
                              <p className="text-sm font-medium text-success">{paymentResult.payment_details.discount_percent}% ({formatCurrency(paymentResult.payment_details.discount_amount)})</p>
                            </div>
                            <div>
                              <p className="text-xs text-muted-foreground">{t("invoices.ui.payBy")}</p>
                              <p className="text-sm font-medium">{paymentResult.payment_details.discount_deadline || paymentResult.payment_details.recommended_pay_date}</p>
                            </div>
                            <div>
                              <p className="text-xs text-muted-foreground">{t("invoices.ui.netAmount")}</p>
                              <p className="text-sm font-mono font-medium">{formatCurrency(paymentResult.payment_details.net_payment_amount)}</p>
                            </div>
                          </>
                        )}
                        {!paymentResult.payment_details?.discount_available && paymentResult.payment_details && (
                          <div>
                            <p className="text-xs text-muted-foreground">{t("invoices.ui.dueDate")}</p>
                            <p className="text-sm font-medium">{paymentResult.payment_details.due_date || selectedItem?.due_date || "--"}</p>
                          </div>
                        )}
                      </div>
                      {paymentResult.reasoning && (
                        <p className="text-xs text-muted-foreground leading-relaxed">{paymentResult.reasoning}</p>
                      )}
                    </div>
                  ) : null}
                </div>
              )}

              {/* Error */}
              {matchResult.error && (
                <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
                  {matchResult.error}
                </div>
              )}

              {/* Footer */}
              {!matchResult.error && (
                <div className="space-y-3 pt-2 border-t">
                  {matchResult.auto_approved || matchResult.match_result === "MATCHED" ? (
                    <div className="flex items-center justify-between">
                      <StatusBadge status="approved">{t("invoices.ui.autoApprovedThreeWayMatch")}</StatusBadge>
                      <div className="flex gap-2">
                        <Button variant="ghost" size="sm" onClick={matchSelected}>Re-analyze</Button>
                        <Button variant="ghost" size="sm" onClick={() => setShowModal(false)}>{t("invoices.ui.close")}</Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <Input
                        placeholder={matchResult.match_result === "DISCREPANCY" ? "Justification required to override..." : "Justification (optional)..."}
                        value={justification} onChange={(e) => setJustification(e.target.value)}
                      />
                      <div className="flex justify-between gap-2">
                        <Button variant="ghost" size="sm" onClick={matchSelected}>Re-analyze</Button>
                        <div className="flex gap-2">
                          <Button variant="destructive" size="sm" disabled={submitting} onClick={async () => {
                            setSubmitting(true);
                            try { await api.recordDecision({ document_type: "INVOICE", document_id: selectedItem?.invoice_id || "", action: "REJECT", justification }); setShowModal(false); setJustification(""); } catch {}
                            setSubmitting(false);
                          }}>{t("invoices.ui.blockPayment")}</Button>
                          <Button size="sm" disabled={submitting || (matchResult.match_result === "DISCREPANCY" && !justification)} onClick={async () => {
                            setSubmitting(true);
                            try { await api.recordDecision({ document_type: "INVOICE", document_id: selectedItem?.invoice_id || "", action: "APPROVE", justification }); setShowModal(false); setJustification(""); } catch {}
                            setSubmitting(false);
                          }}>{submitting ? "Submitting..." : "Override & Approve"}</Button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      {/* Payment Analysis Modal (standalone) */}
      <Dialog open={showPaymentModal} onOpenChange={setShowPaymentModal}>
        <DialogContent size="large">
          <DialogHeader><DialogTitle>{t("invoices.ui.paymentAgentSchedulingAnalysis")}</DialogTitle></DialogHeader>
          {runningPayment && !paymentResult ? (
            <div className="space-y-4 py-4">
              <div className="flex items-center gap-3">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                <span className="text-sm font-medium">{t("invoices.ui.analyzingPaymentSchedule")}</span>
              </div>
              {paymentAgent.progress.length > 0 && (
                <div className="space-y-1.5 pl-8">
                  {paymentAgent.progress.map((step, i) => <p key={i} className="text-sm text-muted-foreground">{step}</p>)}
                </div>
              )}
            </div>
          ) : paymentResult ? (
            <PaymentResultView result={paymentResult} />
          ) : null}
        </DialogContent>
      </Dialog>

      {/* Schedule Payment Workflow Modal */}
      <Dialog open={showScheduleModal} onOpenChange={setShowScheduleModal}>
        <DialogContent size="large">
          <DialogHeader><DialogTitle>{t("invoices.ui.schedulePaymentWorkflow")}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            {/* Step 1: 3-Way Match */}
            <div className="flex gap-3">
              <div className="flex flex-col items-center">
                {matchResult && !matchResult.error ? (
                  <CheckCircle2 className="h-5 w-5 text-success shrink-0" />
                ) : matching ? (
                  <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />
                ) : (
                  <Circle className="h-5 w-5 text-muted-foreground/30 shrink-0" />
                )}
                <div className="w-px flex-1 bg-border mt-1" />
              </div>
              <div className="flex-1 pb-4">
                <p className="text-sm font-medium">{t("invoices.ui.threeWayMatch")}</p>
                {matching && <p className="text-xs text-muted-foreground mt-1">{t("invoices.ui.comparingInvoice")}</p>}
                {matchResult && !matchResult.error && (
                  <div className="flex items-center gap-2 mt-1">
                    <StatusBadge status={matchResult.match_result === "MATCHED" ? "matched" : "warning"}>{matchResult.match_result}</StatusBadge>
                    <span className="text-xs text-muted-foreground">{((matchResult.confidence || 0) * 100).toFixed(0)}% confidence</span>
                  </div>
                )}
                {matchResult?.error && <p className="text-xs text-destructive mt-1">{matchResult.error}</p>}
              </div>
            </div>

            {/* Step 2: Payment Analysis */}
            <div className="flex gap-3">
              <div className="flex flex-col items-center">
                {paymentResult && !paymentResult.error ? (
                  <CheckCircle2 className="h-5 w-5 text-success shrink-0" />
                ) : runningPayment ? (
                  <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />
                ) : (
                  <Circle className="h-5 w-5 text-muted-foreground/30 shrink-0" />
                )}
                <div className="w-px flex-1 bg-border mt-1" />
              </div>
              <div className="flex-1 pb-4">
                <p className="text-sm font-medium">{t("invoices.ui.paymentAnalysis")}</p>
                {runningPayment && !paymentResult && <p className="text-xs text-muted-foreground mt-1">{t("invoices.ui.analyzingPaymentTerms")}</p>}
                {paymentResult && !paymentResult.error && (
                  <div className="mt-2">
                    <PaymentResultView result={paymentResult} />
                  </div>
                )}
                {paymentResult?.error && <p className="text-xs text-destructive mt-1">{paymentResult.error}</p>}
              </div>
            </div>

            {/* Step 3: Schedule Payment */}
            <div className="flex gap-3">
              <div className="flex flex-col items-center">
                {paymentCreated && !paymentCreated.error ? (
                  <CheckCircle2 className="h-5 w-5 text-success shrink-0" />
                ) : schedulingPayment ? (
                  <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />
                ) : paymentResult && !paymentResult.error ? (
                  <Circle className="h-5 w-5 text-primary shrink-0" />
                ) : (
                  <Circle className="h-5 w-5 text-muted-foreground/30 shrink-0" />
                )}
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium">{t("invoices.ui.schedulePayment")}</p>
                {paymentCreated?.error && (
                  <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive mt-2">{paymentCreated.error}</div>
                )}
                {paymentCreated && !paymentCreated.error && (
                  <div className="rounded-lg border border-success/50 bg-success/5 p-3 mt-2">
                    <p className="text-sm font-medium text-success">{t("invoices.ui.paymentScheduledSuccessfully")}</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {paymentCreated.payment_id} -- {formatCurrency(paymentCreated.amount)} via {paymentCreated.mode_of_payment || "Wire Transfer"}
                    </p>
                  </div>
                )}
                {paymentResult && !paymentResult.error && !paymentCreated && (
                  <div className="flex items-center justify-between mt-2">
                    <div className="text-sm">
                      <span className="text-muted-foreground">{t("invoices.ui.amountLabel")} </span>
                      <span className="font-mono font-medium">
                        {formatCurrency(paymentResult.payment_details?.net_payment_amount || selectedItem?.outstanding_amount || selectedItem?.total_amount || 0)}
                      </span>
                      {paymentResult.payment_details?.discount_available && (
                        <span className="text-success text-xs ml-2">{t("invoices.ui.savingWithDiscount", { amount: formatCurrency(paymentResult.payment_details.discount_amount), percent: paymentResult.payment_details.discount_percent })}</span>
                      )}
                    </div>
                    <Button size="sm" onClick={confirmSchedulePayment} loading={schedulingPayment}>
                      {t("invoices.ui.confirmSchedule")}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Upload Modal */}
      <Dialog open={showUploadModal} onOpenChange={setShowUploadModal}>
        <DialogContent size="large">
          <DialogHeader><DialogTitle>{t("invoices.ui.invoiceExtraction")}</DialogTitle></DialogHeader>
          {uploading && (
            <div className="flex flex-col items-center gap-3 py-12">
              <Spinner size="lg" />
              <p className="text-sm text-muted-foreground">{extractionResult?._step || t("invoices.ui.analyzingInvoiceWithBedrock")}</p>
            </div>
          )}
          {!uploading && extractionResult && (
            <div className="space-y-4">
              {extractionResult.error ? (
                <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-4 text-sm text-destructive">{extractionResult.error}</div>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">{t("invoices.ui.confidenceLabel")}</span>
                    <StatusBadge status={extractionResult.confidence?.tier === "AUTO_ACCEPT" ? "approved" : extractionResult.confidence?.tier === "REVIEW" ? "warning" : "error"}>
                      {extractionResult.confidence?.tier || "UNKNOWN"}
                    </StatusBadge>
                    <span className="text-xs text-muted-foreground">({extractionResult.confidence?.overall?.toFixed(0) || 0}% overall)</span>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {[
                      ["Vendor", extractionResult.vendor_name],
                      ["Invoice #", extractionResult.invoice_number],
                      ["Total", extractionResult.total_amount ? formatCurrency(parseFloat(extractionResult.total_amount)) : "--"],
                      ["PO Reference", extractionResult.po_number],
                      ["Invoice Date", extractionResult.invoice_date],
                      ["Due Date", extractionResult.due_date],
                    ].map(([label, value]) => (
                      <div key={label as string}>
                        <div className="text-xs font-medium text-muted-foreground">{label}</div>
                        <div className="text-sm font-medium mt-0.5">{value || "--"}</div>
                      </div>
                    ))}
                  </div>
                  {extractionResult.line_items?.length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-muted-foreground mb-2">{t("invoices.ui.lineItems", { count: extractionResult.line_items.length })}</div>
                      <Table>
                        <TableHeader><TableRow>
                          <TableHead>{t("invoices.ui.itemCode")}</TableHead><TableHead>{t("invoices.ui.description")}</TableHead>
                          <TableHead className="text-right">{t("invoices.ui.qty")}</TableHead><TableHead className="text-right">{t("invoices.ui.unitPrice")}</TableHead>
                          <TableHead className="text-right">{t("invoices.ui.amount")}</TableHead>
                        </TableRow></TableHeader>
                        <TableBody>
                          {extractionResult.line_items.map((li: any, i: number) => (
                            <TableRow key={i}>
                              <TableCell className="font-mono text-xs">{li.item_code || "--"}</TableCell>
                              <TableCell className="text-sm">{li.description || "--"}</TableCell>
                              <TableCell className="text-right">{li.quantity ?? "--"}</TableCell>
                              <TableCell className="text-right">{li.unit_price != null ? formatCurrency(li.unit_price) : "--"}</TableCell>
                              <TableCell className="text-right font-mono">{li.amount != null ? formatCurrency(li.amount) : "--"}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </>
              )}
              {createdInvoice && (
                <div className="rounded-lg border border-success/50 bg-success/5 p-3">
                  <p className="text-sm font-medium text-success">{t("invoices.ui.invoiceCreatedInErp")}</p>
                  <p className="text-xs text-muted-foreground mt-1">{createdInvoice.invoice_id} -- {createdInvoice.supplier_name || createdInvoice.supplier_id} -- {formatCurrency(createdInvoice.total_amount)}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{t("invoices.ui.selectFromListAndMatch")}</p>
                </div>
              )}
              <div className="flex justify-end pt-2 border-t">
                <Button variant="ghost" size="sm" onClick={() => { setShowUploadModal(false); setCreatedInvoice(null); }}>{t("invoices.ui.close")}</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ---------- Payment Result View (reused in multiple modals) ---------- */
function PaymentResultView({ result }: { result: any }) {
  const { t } = useTranslation();
  if (result.error) {
    return <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">{result.error}</div>;
  }
  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("invoices.ui.paymentRecommendation")}</p>
        <StatusBadge status={result.payment_recommendation === "PAY_AT_DISCOUNT" || result.payment_recommendation === "PAY_NOW" ? "approved" : "submitted"}>
          {result.payment_recommendation}
        </StatusBadge>
      </div>
      {result.payment_details && (
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("invoices.ui.paymentDetails")}</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 rounded-lg border p-4">
            <div>
              <p className="text-xs text-muted-foreground">{t("invoices.ui.invoiceAmount")}</p>
              <p className="text-sm font-mono font-medium">{formatCurrency(result.payment_details.invoice_amount)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("invoices.ui.discountAvailable")}</p>
              <p className="text-sm font-medium">{result.payment_details.discount_available ? t("invoices.ui.discountAvailableYes", { percent: result.payment_details.discount_percent }) : t("invoices.ui.no")}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("invoices.ui.discountAmount")}</p>
              <p className="text-sm font-mono font-medium">{formatCurrency(result.payment_details.discount_amount)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("invoices.ui.dueDate")}</p>
              <p className="text-sm font-medium">{result.payment_details.due_date}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("invoices.ui.recommendedPayDate")}</p>
              <p className="text-sm font-medium">{result.payment_details.recommended_pay_date}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("invoices.ui.netPayment")}</p>
              <p className="text-sm font-mono font-medium">{formatCurrency(result.payment_details.net_payment_amount)}</p>
            </div>
          </div>
        </div>
      )}
      {result.annualized_discount_rate > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("invoices.ui.annualizedDiscountRate")}</p>
          <p className="text-2xl font-bold">{result.annualized_discount_rate}%</p>
        </div>
      )}
      {result.reasoning && (
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("invoices.ui.reasoning")}</p>
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{result.reasoning}</p>
        </div>
      )}
      {result.flags?.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("invoices.ui.flags")}</p>
          <div className="space-y-1.5">
            {result.flags.map((f: string, i: number) => {
              const lower = f.toLowerCase();
              const isPositive = lower.startsWith("positive");
              const isAction = lower.startsWith("action required");
              const isInfo = lower.startsWith("info");
              const label = f.replace(/^(POSITIVE|ACTION REQUIRED|INFO|WARNING|NEGATIVE):\s*/i, "");
              return (
                <div key={i} className={cn(
                  "flex items-start gap-2 text-sm rounded-md px-3 py-1.5",
                  isPositive ? "bg-success/5" : isAction ? "bg-amber-50 dark:bg-amber-950/20" : isInfo ? "bg-blue-50 dark:bg-blue-950/20" : "bg-muted/30"
                )}>
                  {isPositive ? (
                    <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" />
                  ) : isAction ? (
                    <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                  ) : isInfo ? (
                    <Circle className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                  )}
                  <span className={cn(
                    isPositive ? "text-success" : isAction ? "text-amber-700 dark:text-amber-400" : isInfo ? "text-blue-700 dark:text-blue-400" : "text-muted-foreground"
                  )}>{label}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
