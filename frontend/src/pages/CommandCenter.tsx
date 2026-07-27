// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState, useCallback } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table";
import { Spinner } from "@/components/ui/spinner";
import { RefreshCw, ClipboardList, Search, ShoppingCart, Package, Receipt, DollarSign } from "lucide-react";
import { api } from "../api";
import type { DecisionRun, ErrorSummary } from "../api";
import { useTranslation } from "react-i18next";

const AGENTS = [
  { name: "Requisition", icon: ClipboardList, key: "requisition", docType: "PR" },
  { name: "Sourcing", icon: Search, key: "sourcing", docType: "PR" },
  { name: "PO Mgmt", icon: ShoppingCart, key: "po_management", docType: "PO" },
  { name: "Receiving", icon: Package, key: "receiving", docType: "GR" },
  { name: "Inv. Match", icon: Receipt, key: "invoice_matching", docType: "INVOICE" },
  { name: "Payment", icon: DollarSign, key: "payment", docType: "INVOICE" },
];

export default function CommandCenter() {
  const { t } = useTranslation();
  const [decisions, setDecisions] = useState<DecisionRun[]>([]);
  const [errors, setErrors] = useState<ErrorSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [decs, errSummary] = await Promise.all([
        api.getDecisions(),
        api.getErrorSummary().catch(() => null),
      ]);
      setDecisions(Array.isArray(decs) ? decs : []);
      setErrors(errSummary);
    } catch {
      // Non-fatal: leave any previously loaded data in place.
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    // Initial load. setState runs only after the awaited fetch resolves, so no
    // synchronous state update happens in the effect body.
    let cancelled = false;
    (async () => {
      try {
        const [decs, errSummary] = await Promise.all([
          api.getDecisions(),
          api.getErrorSummary().catch(() => null),
        ]);
        if (cancelled) return;
        setDecisions(Array.isArray(decs) ? decs : []);
        setErrors(errSummary);
      } catch {
        // Non-fatal on initial load.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const sorted = [...decisions].sort((a, b) => (b.decided_at || b.timestamp || "").localeCompare(a.decided_at || a.timestamp || ""));

  return (
    <div className="animate-in space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {t("commandCenter.ui.title")} <span className="text-base font-normal text-muted-foreground ml-2">{t("commandCenter.ui.totalDecisions", { count: decisions.filter(d => d.action === "APPROVE" || d.action === "REJECT").length })}</span>
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{t("commandCenter.ui.subtitle")}</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {(() => {
          const workflows = decisions.filter(d => d.type === "workflow");
          // analyses not shown in KPIs — only in per-agent fleet status
          const decs = decisions.filter(d => d.type === "decision");
          const aiApproved = decs.filter(d => d.action === "AI_APPROVED");
          const aiRejected = decs.filter(d => d.action === "AI_REJECTED");
          const humanApproved = decs.filter(d => d.action === "HUMAN_APPROVED");
          const humanRejected = decs.filter(d => d.action === "HUMAN_REJECTED");
          const escalated = decs.filter(d => d.action === "AI_ESCALATED");
          return [
            { label: "Total Runs", val: workflows.length, color: "text-primary" },
            { label: "AI Approved", val: aiApproved.length, color: "text-success" },
            { label: "AI Rejected", val: aiRejected.length, color: "text-destructive" },
            { label: "Human Approved", val: humanApproved.length, color: "text-blue-500" },
            { label: "Human Rejected", val: humanRejected.length, color: "text-destructive" },
            { label: "Pending", val: escalated.length, color: "text-amber-500" },
          ];
        })().map((kpi, i) => (
          <div key={i} className="rounded-lg border bg-card p-4">
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{kpi.label}</div>
            <div className={`text-3xl font-bold mt-1 ${kpi.color}`}>{kpi.val}</div>
          </div>
        ))}
      </div>

      {/* Agent Pipeline */}
      <div className="rounded-lg border bg-card p-5">
        <div className="text-sm font-semibold mb-4">{t("commandCenter.ui.agentFleetStatus")}</div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {AGENTS.map((agent) => {
            // Error summaries may carry per-agent counts alongside the typed
            // fields; read them defensively without asserting the shape.
            const agentErrorCount = (errors as Record<string, number> | null)?.[agent.key];
            const hasError = typeof agentErrorCount === "number" && agentErrorCount > 0;
            const agentDecs = decisions.filter(d =>
              d.agent === agent.key || (d.document_type || "").toUpperCase() === agent.docType
            );
            const count = agentDecs.length;
            return (
              <div
                key={agent.key}
                className={`rounded-lg border p-3 text-center transition-colors ${hasError ? "border-destructive/50 bg-destructive/5" : "border-success/30 bg-success/5"}`}
              >
                <div className="flex justify-center"><agent.icon className="h-6 w-6" /></div>
                <div className="text-xs font-semibold mt-1">{agent.name}</div>
                <div className={`text-xs mt-1 ${hasError ? "text-destructive" : "text-success"}`}>
                  {hasError ? "Warning" : "Ready"}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {count > 0 ? `${count} processed` : "Idle"}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Activity Log + Comparison */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Activity Log */}
        <div className="rounded-lg border bg-card p-5 max-h-96 flex flex-col">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">{t("commandCenter.ui.agentActivityLog")}</div>
          <div className="flex-1 overflow-y-auto space-y-0.5">
            {sorted.slice(0, 15).map((d, i) => {
              const ts = d.decided_at || d.timestamp || "";
              const agentType = d.agent || d.decided_by || d.type || "unknown";
              const label = d.type === "workflow" ? "Workflow" : d.type === "analysis" ? (d.agent || "Analysis") : (d.action || d.type || "");
              return (
                <div key={i} className="flex items-center gap-2 py-1.5 text-xs border-b border-border/50 last:border-0">
                  <span className="text-muted-foreground font-mono w-16 shrink-0">{ts.substring(11, 19) || "--"}</span>
                  <span className="flex-1 truncate"><strong>{label}</strong> {d.document_id} -- {d.document_type}</span>
                  <span className="text-xs text-muted-foreground shrink-0">{agentType.replace(/_/g, " ")}</span>
                </div>
              );
            })}
            {sorted.length === 0 && (
              <div className="text-center text-muted-foreground py-8 text-sm">{t("commandCenter.ui.noActivityYet")}</div>
            )}
          </div>
        </div>

        {/* Legacy vs Agentic */}
        <div className="rounded-lg border bg-card p-5">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">{t("commandCenter.ui.legacyVsAgenticImpact")}</div>
          <div className="grid grid-cols-[1fr_auto_1fr] gap-0">
            <div className="px-4">
              <div className="text-xs font-bold uppercase tracking-wider text-destructive mb-3 pb-2 border-b">{t("commandCenter.ui.legacyProcess")}</div>
              {[
                ["Cycle Time", "14-30 days"],
                ["Cost / Invoice", "$24.50"],
                ["Touchless Rate", "25%"],
                ["Exception Rate", "35-40%"],
                ["Manual Handoffs", "9+"],
              ].map(([label, val]) => (
                <div key={label} className="flex justify-between py-1.5 text-xs">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-medium text-destructive">{val}</span>
                </div>
              ))}
            </div>
            <div className="w-px bg-border" />
            <div className="px-4">
              <div className="text-xs font-bold uppercase tracking-wider text-success mb-3 pb-2 border-b">{t("commandCenter.ui.aria")}</div>
              {[
                ["Cycle Time", "2.4 hours"],
                ["Cost / Invoice", "$3.20"],
                ["Touchless Rate", "87.3%"],
                ["Exception Rate", "4.2%"],
                ["Manual Handoffs", "0"],
              ].map(([label, val]) => (
                <div key={label} className="flex justify-between py-1.5 text-xs">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-medium text-success">{val}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Recent Transactions Table */}
      <div className="rounded-lg border bg-card">
        <div className="px-5 py-3 border-b">
          <h2 className="text-base font-semibold">{t("commandCenter.ui.recentTransactions", { count: sorted.slice(0, 25).length })}</h2>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Spinner size="lg" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("commandCenter.ui.time")}</TableHead>
                <TableHead>{t("commandCenter.ui.document")}</TableHead>
                <TableHead>{t("commandCenter.ui.type")}</TableHead>
                <TableHead>{t("commandCenter.ui.action")}</TableHead>
                <TableHead>{t("commandCenter.ui.decidedBy")}</TableHead>
                <TableHead>{t("commandCenter.ui.confidence")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    {t("commandCenter.ui.noActivityRecorded")}
                  </TableCell>
                </TableRow>
              ) : (
                sorted.slice(0, 25).map((item: DecisionRun, i: number) => {
                  const ts = item.decided_at || item.timestamp || "";
                  const actionLabel = item.type === "workflow" ? "Workflow" : item.type === "analysis" ? (item.agent || "Analysis") : (item.action || item.type || "--");
                  return (
                    <TableRow key={i}>
                      <TableCell className="text-xs whitespace-nowrap">{ts.substring(0, 19)?.replace("T", " ") || "--"}</TableCell>
                      <TableCell className="font-mono text-xs text-primary">{item.document_id || "--"}</TableCell>
                      <TableCell className="text-xs">{item.document_type || "--"}</TableCell>
                      <TableCell>
                        {item.action === "APPROVE" || (item.action || "").includes("APPROVE") ? (
                          <StatusBadge status="approved">{actionLabel}</StatusBadge>
                        ) : item.action === "REJECT" || (item.action || "").includes("REJECT") ? (
                          <StatusBadge status="rejected">{actionLabel}</StatusBadge>
                        ) : (
                          <StatusBadge status="info">{actionLabel}</StatusBadge>
                        )}
                      </TableCell>
                      <TableCell className="text-sm">{item.decided_by || item.agent || "--"}</TableCell>
                      <TableCell className="text-sm">
                        {item.confidence != null && Number(item.confidence) > 0
                          ? `${Math.round(Number(item.confidence) * 100)}%`
                          : item.agent_confidence != null && Number(item.agent_confidence) > 0
                            ? `${Math.round(Number(item.agent_confidence) * 100)}%`
                            : "--"}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
