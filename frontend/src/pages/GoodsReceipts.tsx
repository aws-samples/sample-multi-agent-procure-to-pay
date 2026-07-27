// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState, useRef } from "react";
import { Search, CheckCircle2, AlertTriangle, XCircle, ChevronDown, ChevronRight, Package } from "lucide-react";
import AgentStepList from "@/components/AgentProgress";
import { erpApi } from "../erpApi";
import type { Receipt, PurchaseOrder } from "../types/p2p";
import { useAgentStream } from "../hooks/useAgentStream";
import { formatCurrency, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { useTranslation } from "react-i18next";

interface POGroup {
  po: PurchaseOrder;
  receipts: Receipt[];
}

export default function GoodsReceipts() {
  const { t } = useTranslation();
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [poMap, setPoMap] = useState<Record<string, PurchaseOrder>>({});
  const [loading, setLoading] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [selectedItem, setSelectedItem] = useState<Receipt | null>(null);
  const [agentResult, setAgentResult] = useState<any>(null);
  const [_agentMeta, setAgentMeta] = useState<any>(null);
  const [verifying, setVerifying] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [expandedPOs, setExpandedPOs] = useState<Set<string>>(new Set());

  const agent = useAgentStream();

  useEffect(() => {
    Promise.all([erpApi.listReceipts(), erpApi.listPurchaseOrders()]).then(
      ([receiptData, poData]) => {
        setReceipts(receiptData.receipts);
        const map: Record<string, PurchaseOrder> = {};
        for (const po of poData.purchase_orders) {
          map[po.order_id] = po;
        }
        setPoMap(map);
        // Auto-expand all POs that have receipts
        const poIds = new Set(receiptData.receipts.map((r: Receipt) => r.order_id).filter(Boolean) as string[]);
        setExpandedPOs(poIds);
        setLoading(false);
      },
    );
  }, []);

  /* ---------- Agent invocation ---------- */
  const verifySelected = async () => {
    if (!selectedItem) return;
    setVerifying(true);
    setShowModal(true);
    setAgentResult(null);
    setAgentMeta(null);
    agent.reset();
    try {
      await agent.invoke("receiving", selectedItem.order_id || selectedItem.receipt_id, {
        order_id: selectedItem.order_id || "",
      });
    } catch {
      /* error in agent.error */
    }
  };

  const prevGrResult = useRef<any>(null);
  useEffect(() => {
    if (agent.result && agent.result !== prevGrResult.current) {
      prevGrResult.current = agent.result;
      setAgentResult(agent.result);
      setAgentMeta(agent.meta);
      setVerifying(false);
    }
    if (agent.error && verifying) {
      setAgentResult({ error: agent.error });
      setVerifying(false);
    }
  }, [agent.result, agent.error]);

  /* ---------- Group receipts by PO ---------- */
  const poGroups: POGroup[] = [];
  const orphanReceipts: Receipt[] = [];
  const receiptsByPO: Record<string, Receipt[]> = {};

  for (const r of receipts) {
    if (r.order_id) {
      if (!receiptsByPO[r.order_id]) receiptsByPO[r.order_id] = [];
      receiptsByPO[r.order_id].push(r);
    } else {
      orphanReceipts.push(r);
    }
  }

  for (const [poId, poReceipts] of Object.entries(receiptsByPO)) {
    const po = poMap[poId] || { order_id: poId, supplier_id: "", status: "unknown", line_items: [] } as PurchaseOrder;
    poGroups.push({ po, receipts: poReceipts });
  }

  // Sort: most recent PO first
  poGroups.sort((a, b) => (b.po.order_date || "").localeCompare(a.po.order_date || ""));

  /* ---------- Filtering ---------- */
  const matchesFilter = (text: string) => text.toLowerCase().includes(filterText.toLowerCase());
  const filteredGroups = filterText
    ? poGroups.filter((g) =>
        matchesFilter(g.po.order_id) ||
        matchesFilter(g.po.supplier_name || "") ||
        g.receipts.some((r) => matchesFilter(r.receipt_id) || matchesFilter(r.status || ""))
      )
    : poGroups;

  const togglePO = (poId: string) => {
    setExpandedPOs((prev) => {
      const next = new Set(prev);
      if (next.has(poId)) next.delete(poId);
      else next.add(poId);
      return next;
    });
  };

  const totalReceipts = filteredGroups.reduce((sum, g) => sum + g.receipts.length, 0) + orphanReceipts.length;

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("goodsReceipts.ui.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("goodsReceipts.ui.subtitle", { totalReceipts, poCount: filteredGroups.length })}
          </p>
        </div>
        <Button size="sm" disabled={!selectedItem} onClick={verifySelected} loading={verifying}>
          {t("goodsReceipts.ui.verifyWithAgent")}
        </Button>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search by PO, receipt, or supplier"
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Data Table — grouped by PO */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : filteredGroups.length === 0 && orphanReceipts.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">{t("goodsReceipts.ui.noReceiptsFound")}</div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"></TableHead>
                <TableHead>{t("goodsReceipts.ui.document")}</TableHead>
                <TableHead>{t("goodsReceipts.ui.supplier")}</TableHead>
                <TableHead>{t("goodsReceipts.ui.date")}</TableHead>
                <TableHead>{t("goodsReceipts.ui.status")}</TableHead>
                <TableHead className="text-right">{t("goodsReceipts.ui.items")}</TableHead>
                <TableHead className="text-right">{t("goodsReceipts.ui.amount")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredGroups.map((group) => {
                const isExpanded = expandedPOs.has(group.po.order_id);
                return (
                  <PurchaseOrderGroup
                    key={group.po.order_id}
                    group={group}
                    isExpanded={isExpanded}
                    onToggle={() => togglePO(group.po.order_id)}
                    selectedReceiptId={selectedItem?.receipt_id}
                    onSelectReceipt={(r) => setSelectedItem(selectedItem?.receipt_id === r.receipt_id ? null : r)}
                  />
                );
              })}
              {/* Orphan receipts (no PO reference) */}
              {orphanReceipts.map((r) => (
                <TableRow
                  key={r.receipt_id}
                  className={cn("cursor-pointer", selectedItem?.receipt_id === r.receipt_id && "bg-muted")}
                  onClick={() => setSelectedItem(selectedItem?.receipt_id === r.receipt_id ? null : r)}
                >
                  <TableCell></TableCell>
                  <TableCell className="font-mono text-xs">{r.receipt_id}</TableCell>
                  <TableCell>{r.supplier_name || "\u2014"}</TableCell>
                  <TableCell>{r.receipt_date || "\u2014"}</TableCell>
                  <TableCell><StatusBadge status={r.status || "unknown"} /></TableCell>
                  <TableCell className="text-right">{r.line_items?.length || 0}</TableCell>
                  <TableCell className="text-right">\u2014</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Agent Verification Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>{t("goodsReceipts.ui.dialogTitle")}</DialogTitle>
          </DialogHeader>

          {verifying ? (
            <div className="py-4">
              <AgentStepList progress={agent.progress} isRunning={verifying} title="Receiving Agent" />
            </div>
          ) : agentResult ? (
            <div className="space-y-5">
              {/* Validation Result */}
              {agentResult.validation_result && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("goodsReceipts.ui.validationResult")}</p>
                  <StatusBadge
                    status={
                      agentResult.validation_result === "ACCEPTED"
                        ? "completed"
                        : agentResult.validation_result === "PARTIAL"
                          ? "partially"
                          : "rejected"
                    }
                  >
                    {agentResult.validation_result}
                  </StatusBadge>
                </div>
              )}

              {/* Reasoning */}
              {agentResult.reasoning && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("goodsReceipts.ui.reasoning")}</p>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{agentResult.reasoning}</p>
                </div>
              )}

              {/* Line Validations */}
              {agentResult.line_validations && agentResult.line_validations.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("goodsReceipts.ui.lineValidations")}</p>
                  <div className="space-y-1.5">
                    {agentResult.line_validations.map((l: any, i: number) => {
                      const status = l.status === "COMPLETE" ? "PASS" : l.status === "PARTIAL" ? "WARN" : "FAIL";
                      return (
                        <div key={i} className="flex items-start gap-2 text-sm">
                          {status === "PASS" ? (
                            <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" />
                          ) : status === "WARN" ? (
                            <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
                          ) : (
                            <XCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
                          )}
                          <div>
                            <span className="font-medium">{t("goodsReceipts.ui.itemLabel", { itemId: l.item_id || "", itemName: l.item_name || "" })}</span>
                            <span className="text-muted-foreground">
                              {" "}PO: {l.po_qty}, Received: {l.total_received_qty}, Open: {l.remaining_open_qty}
                              {l.on_time === false ? " -- LATE" : ""}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Receipt Line Items table */}
              {selectedItem && selectedItem.line_items?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("goodsReceipts.ui.receiptLineItems")}</p>
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("goodsReceipts.ui.item")}</TableHead>
                          <TableHead>{t("goodsReceipts.ui.description")}</TableHead>
                          <TableHead className="text-right">{t("goodsReceipts.ui.qtyReceived")}</TableHead>
                          <TableHead className="text-right">{t("goodsReceipts.ui.rejectedQty")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {selectedItem.line_items.map((li: any, idx: number) => (
                          <TableRow key={idx}>
                            <TableCell>{li.item_id}</TableCell>
                            <TableCell>{li.item_name || "\u2014"}</TableCell>
                            <TableCell className="text-right">{li.quantity_received}</TableCell>
                            <TableCell className="text-right">{li.rejected_quantity || 0}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
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

/* ---------- PO Group Component ---------- */

function PurchaseOrderGroup({
  group,
  isExpanded,
  onToggle,
  selectedReceiptId,
  onSelectReceipt,
}: {
  group: POGroup;
  isExpanded: boolean;
  onToggle: () => void;
  selectedReceiptId?: string;
  onSelectReceipt: (r: Receipt) => void;
}) {
  const { po, receipts } = group;
  const [expandedGRs, setExpandedGRs] = useState<Set<string>>(new Set());

  const toggleGR = (receiptId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedGRs((prev) => {
      const next = new Set(prev);
      if (next.has(receiptId)) next.delete(receiptId);
      else next.add(receiptId);
      return next;
    });
  };

  return (
    <>
      {/* PO Header Row */}
      <TableRow
        className="cursor-pointer bg-muted/30 hover:bg-muted/50"
        onClick={onToggle}
      >
        <TableCell className="w-8">
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </Button>
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-2">
            <Package className="h-4 w-4 text-blue-500" />
            <span className="font-semibold text-sm">{po.order_id}</span>
            <span className="text-xs text-muted-foreground">({receipts.length} GR{receipts.length !== 1 ? "s" : ""})</span>
          </div>
        </TableCell>
        <TableCell className="font-medium">{po.supplier_name || "\u2014"}</TableCell>
        <TableCell>{po.order_date || "\u2014"}</TableCell>
        <TableCell><StatusBadge status={po.status || "unknown"} /></TableCell>
        <TableCell className="text-right">{po.line_items?.length || "\u2014"}</TableCell>
        <TableCell className="text-right font-medium">
          {po.total_amount != null ? formatCurrency(po.total_amount) : "\u2014"}
        </TableCell>
      </TableRow>

      {/* PO Line Items — use table rows aligned to parent columns */}
      {isExpanded && po.line_items?.length > 0 && po.line_items.map((li: any, i: number) => (
        <TableRow key={`po-item-${i}`} className="bg-muted/10 text-xs">
          <TableCell></TableCell>
          <TableCell className="py-1">
            <span className="ml-4 font-mono text-muted-foreground">{li.item_id}</span>
            {li.item_name && <span className="ml-1.5">{li.item_name}</span>}
          </TableCell>
          <TableCell className="py-1"></TableCell>
          <TableCell className="py-1"></TableCell>
          <TableCell className="py-1"></TableCell>
          <TableCell className="py-1 text-right tabular-nums">{li.quantity}</TableCell>
          <TableCell className="py-1 text-right tabular-nums">{li.unit_price != null ? formatCurrency(li.unit_price) : ""} {li.line_amount != null ? <span className="font-medium ml-2">{formatCurrency(li.line_amount)}</span> : ""}</TableCell>
        </TableRow>
      ))}

      {/* Receipt Rows + collapsible line items */}
      {isExpanded && receipts.map((r) => {
        const grExpanded = expandedGRs.has(r.receipt_id);
        const hasItems = r.line_items?.length > 0;
        return (
          <React.Fragment key={r.receipt_id}>
            <TableRow
              className={cn(
                "cursor-pointer",
                selectedReceiptId === r.receipt_id ? "bg-primary/10" : "bg-card",
              )}
              onClick={() => onSelectReceipt(r)}
            >
              <TableCell>
                {hasItems ? (
                  <Button variant="ghost" size="sm" className="h-5 w-5 p-0 ml-2" onClick={(e) => toggleGR(r.receipt_id, e)}>
                    {grExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  </Button>
                ) : (
                  <span className="inline-block w-4 ml-2 border-l border-b border-muted-foreground/30 h-3" />
                )}
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-primary">{r.receipt_id}</span>
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">{r.supplier_name || "\u2014"}</TableCell>
              <TableCell className="text-sm">{r.receipt_date || "\u2014"}</TableCell>
              <TableCell><StatusBadge status={r.status || "unknown"} /></TableCell>
              <TableCell className="text-right text-sm">{r.line_items?.length || 0}</TableCell>
              <TableCell></TableCell>
            </TableRow>

            {/* GR Line Items — collapsible */}
            {grExpanded && hasItems && r.line_items.map((li: any, i: number) => (
              <TableRow key={`gr-item-${r.receipt_id}-${i}`} className="text-xs bg-card">
                <TableCell></TableCell>
                <TableCell className="py-1">
                  <span className="ml-8 font-mono text-muted-foreground">{li.item_id}</span>
                  {li.item_name && <span className="ml-1.5">{li.item_name}</span>}
                </TableCell>
                <TableCell className="py-1"></TableCell>
                <TableCell className="py-1"></TableCell>
                <TableCell className="py-1"></TableCell>
                <TableCell className="py-1 text-right tabular-nums">{li.quantity_received}</TableCell>
                <TableCell className="py-1 text-right tabular-nums text-muted-foreground">{li.rejected_quantity ? <span className="text-destructive">{li.rejected_quantity} rejected</span> : ""}</TableCell>
              </TableRow>
            ))}
          </React.Fragment>
        );
      })}
    </>
  );
}
