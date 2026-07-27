// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from "react";
import { Search, CheckCircle2 } from "lucide-react";
import AgentStepList from "@/components/AgentProgress";
import { erpApi } from "../erpApi";
import type { Requisition } from "../types/p2p";
import { useAgentStream } from "../hooks/useAgentStream";
import { formatCurrency, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { useTranslation } from "react-i18next";

/** A supplier scored by the sourcing agent. */
interface SupplierEvaluation {
  supplier_id?: string;
  supplier_name?: string;
  score?: number;
  price_score?: number;
  delivery_score?: number;
  quality_score?: number;
  capacity_score?: number;
  total_score?: number;
  notes?: string;
}

/** Result shape returned by the sourcing agent (supports legacy vendor_* keys). */
interface SourcingResult {
  recommended_supplier?: SupplierEvaluation;
  recommended_vendor?: SupplierEvaluation;
  supplier_evaluations?: SupplierEvaluation[];
  vendor_evaluations?: SupplierEvaluation[];
  reasoning?: string;
  consolidation_opportunity?: string;
  error?: string;
}

export default function Sourcing() {
  const { t } = useTranslation();
  const [allItems, setAllItems] = useState<Requisition[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedItem, setSelectedItem] = useState<Requisition | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [filterText, setFilterText] = useState("");

  const agent = useAgentStream();

  // Derive display state directly from the agent stream — no mirroring effect.
  const evaluating = agent.isRunning;
  const agentResult: SourcingResult | null = agent.error
    ? { error: agent.error }
    : (agent.result as SourcingResult | null);

  useEffect(() => {
    erpApi.listRequisitions().then((data) => {
      // Show requisitions that are submitted/approved -- ready for sourcing
      // Adapter normalizes statuses to lowercase canonical values:
      //   ERPNext "Pending" -> "pending_approval", "Ordered" -> "ordered",
      //   "Partially Ordered" -> "approved", "Submitted" -> "submitted"
      const available = data.requisitions.filter(
        (r) =>
          r.status === "pending_approval" ||
          r.status === "approved" ||
          r.status === "ordered" ||
          r.status === "submitted",
      );
      setAllItems(available);
      setLoading(false);
    });
  }, []);

  const evaluateSelected = async () => {
    if (!selectedItem) return;
    setShowModal(true);
    agent.reset();
    try {
      await agent.invoke("sourcing", selectedItem.requisition_id);
    } catch {
      /* error surfaced via agent.error */
    }
  };

  const filtered = filterText
    ? allItems.filter((r) =>
        [r.requisition_id, r.requester, r.status]
          .filter(Boolean)
          .some((v) => v!.toLowerCase().includes(filterText.toLowerCase())),
      )
    : allItems;

  // Backward compat: accept both recommended_supplier and recommended_vendor (legacy)
  const recommendedSupplier = agentResult?.recommended_supplier || agentResult?.recommended_vendor || null;
  const supplierEvaluations = agentResult?.supplier_evaluations || agentResult?.vendor_evaluations || [];

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("sourcing.ui.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t("sourcing.ui.subtitle")}
        </p>
      </div>

      {/* Toolbar: search + agent action */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t("sourcing.ui.searchPlaceholder")}
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            className="pl-9"
          />
        </div>
        {selectedItem && (
          <Button size="sm" disabled={!selectedItem} onClick={evaluateSelected} loading={evaluating}>
            {t("sourcing.ui.evaluateVendors")}
          </Button>
        )}
      </div>

      {/* Data Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">{t("sourcing.ui.noRequisitions")}</div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("sourcing.ui.colRequisitionId")}</TableHead>
                <TableHead>{t("sourcing.ui.colRequester")}</TableHead>
                <TableHead>{t("sourcing.ui.colStatus")}</TableHead>
                <TableHead className="text-right">{t("sourcing.ui.colTotalAmount")}</TableHead>
                <TableHead className="text-right">{t("sourcing.ui.colLineItems")}</TableHead>
                <TableHead>{t("sourcing.ui.colMaterials")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <TableRow
                  key={item.requisition_id}
                  className={cn(
                    "cursor-pointer",
                    selectedItem?.requisition_id === item.requisition_id && "bg-muted",
                  )}
                  onClick={() => setSelectedItem(selectedItem?.requisition_id === item.requisition_id ? null : item)}
                >
                  <TableCell className="font-medium">{item.requisition_id}</TableCell>
                  <TableCell>{item.requester || "--"}</TableCell>
                  <TableCell><StatusBadge status={item.status || "unknown"} /></TableCell>
                  <TableCell className="text-right font-mono">
                    {item.total_amount != null ? formatCurrency(item.total_amount) : "--"}
                  </TableCell>
                  <TableCell className="text-right">{item.line_items?.length || 0}</TableCell>
                  <TableCell className="max-w-[200px] truncate">
                    {item.line_items?.map((li) => li.item_name || li.item_id).join(", ").substring(0, 50) || ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Sourcing Agent Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>{t("sourcing.ui.agentTitle")}</DialogTitle>
          </DialogHeader>

          {evaluating ? (
            <div className="py-4">
              <AgentStepList progress={agent.progress} isRunning={evaluating} title="Sourcing Agent" />
            </div>
          ) : agentResult ? (
            <div className="space-y-5">
              {/* Recommended Supplier */}
              {recommendedSupplier && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("sourcing.ui.recommendedSupplier")}</p>
                  <div className="grid grid-cols-3 gap-4 rounded-lg border p-4">
                    <div>
                      <p className="text-xs text-muted-foreground">{t("sourcing.ui.supplier")}</p>
                      <p className="text-sm font-medium">
                        {recommendedSupplier.supplier_name || recommendedSupplier.supplier_id}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("sourcing.ui.supplierId")}</p>
                      <p className="text-sm font-medium">{recommendedSupplier.supplier_id}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("sourcing.ui.overallScore")}</p>
                      <p className="text-2xl font-bold">{recommendedSupplier.score}/100</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Supplier Evaluations Table */}
              {supplierEvaluations.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{t("sourcing.ui.supplierComparison")}</p>
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("sourcing.ui.supplier")}</TableHead>
                          <TableHead>{t("sourcing.ui.colPrice")}</TableHead>
                          <TableHead>{t("sourcing.ui.colDelivery")}</TableHead>
                          <TableHead>{t("sourcing.ui.colQuality")}</TableHead>
                          <TableHead>{t("sourcing.ui.colCapacity")}</TableHead>
                          <TableHead>{t("sourcing.ui.colScore")}</TableHead>
                          <TableHead>{t("sourcing.ui.colNotes")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {supplierEvaluations.map((e: SupplierEvaluation, i: number) => (
                          <TableRow key={i}>
                            <TableCell className="font-medium">{e.supplier_name || e.supplier_id}</TableCell>
                            <TableCell>{e.price_score}/100</TableCell>
                            <TableCell>{e.delivery_score}/100</TableCell>
                            <TableCell>{e.quality_score}/100</TableCell>
                            <TableCell>{e.capacity_score}/100</TableCell>
                            <TableCell>
                              <StatusBadge
                                status={
                                  (e.total_score ?? 0) >= 70 ? "approved"
                                  : (e.total_score ?? 0) >= 50 ? "warning"
                                  : "rejected"
                                }
                              >
                                {e.total_score}/100
                              </StatusBadge>
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground max-w-[200px]">
                              {e.notes || ""}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}

              {/* Reasoning */}
              {agentResult.reasoning && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("sourcing.ui.reasoning")}</p>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{agentResult.reasoning}</p>
                </div>
              )}

              {/* Consolidation Opportunity */}
              {agentResult.consolidation_opportunity && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{t("sourcing.ui.consolidationOpportunity")}</p>
                  <div className="flex items-start gap-2 rounded-lg border border-success/30 bg-success/5 p-3">
                    <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" />
                    <p className="text-sm">{agentResult.consolidation_opportunity}</p>
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
