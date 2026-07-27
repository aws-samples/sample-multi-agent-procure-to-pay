// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState, useRef } from "react";
import { Search, RefreshCw, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import AgentStepList, { deriveWorkflowSteps, deriveRejectionSteps } from "@/components/AgentProgress";
import { erpApi } from "../erpApi";
import { api } from "../api";
import type { Requisition, RequisitionLineItem, AgentFinding } from "../types/p2p";
import { useAuth } from "../AuthContext";
import { resolveRole } from "../roles";
import { useAgentStream } from "../hooks/useAgentStream";
import { formatCurrency, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";

/* ---------- Local agent-result shapes ---------- */
interface SourcingResult {
  recommended_vendor?: { supplier_name?: string; supplier_id?: string; score?: number } | null;
  reasoning?: string;
}
interface POResult {
  action?: string;
  reasoning?: string;
  created_order_id?: string;
}
/** Normalized shape rendered in the analysis / workflow modal. */
interface AgentResult {
  recommendation?: string;
  risk_level?: string;
  confidence?: number;
  reasoning?: string;
  findings?: AgentFinding[];
  auto_approved?: boolean;
  workflow?: boolean;
  workflow_status?: string;
  current_step?: string;
  workflow_steps?: WorkflowStep[];
  sourcing_result?: SourcingResult | null;
  po_result?: POResult | null;
  created_order_id?: string;
  erp_action_taken?: string;
  error?: string;
}
interface WorkflowStep {
  agent?: string;
  result?: Record<string, unknown>;
}
/** Raw result payload emitted by the workflow agent stream. */
interface RawWorkflowResult {
  steps?: WorkflowStep[];
  recommendation?: string;
  status?: string;
  risk_level?: string;
  confidence?: number;
  reasoning?: string;
  message?: string;
  error?: string;
  findings?: AgentFinding[];
  auto_approved?: boolean;
  workflow_status?: string;
  sourcing_result?: SourcingResult;
  recommended_vendor?: SourcingResult["recommended_vendor"];
  po_result?: POResult;
  created_order_id?: string;
  erp_action_taken?: string;
}
/** A run-history entry (workflow / decision / agent run). */
interface RunEntry {
  id?: string;
  parent_id?: string;
  type?: string;
  agent?: string;
  status?: string;
  action?: string;
  recommendation?: string;
  confidence?: number | string;
  started_at?: string;
  summary?: string;
  result?: Record<string, unknown>;
}

/* ---------- Budget Impact Indicator ---------- */
function BudgetImpactIndicator({ findings }: { findings: AgentFinding[] }) {
  const budgetFindings = findings.filter((f) => f.check?.toLowerCase().includes("budget"));
  if (budgetFindings.length === 0) return null;

  const hasOverrun = budgetFindings.some((f) => f.status === "FAIL");
  const hasWarning = budgetFindings.some((f) => f.status === "WARN");

  const detail = budgetFindings[0]?.detail || "";
  const remainingMatch = detail.match(/remaining[:\s]*\$?([\d,]+(?:\.\d+)?)/i);
  const budgetMatch = detail.match(/budget[:\s]*\$?([\d,]+(?:\.\d+)?)/i);
  const committedMatch = detail.match(/committed[:\s]*\$?([\d,]+(?:\.\d+)?)/i);

  const color = hasOverrun ? "destructive" : hasWarning ? "warning" : "success";

  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        color === "destructive" && "border-destructive/50 bg-destructive/5",
        color === "warning" && "border-warning/50 bg-warning/5",
        color === "success" && "border-success/50 bg-success/5",
      )}
    >
      <div className="flex items-center gap-2 mb-2">
        {hasOverrun ? (
          <XCircle className="h-4 w-4 text-destructive" />
        ) : hasWarning ? (
          <AlertTriangle className="h-4 w-4 text-warning" />
        ) : (
          <CheckCircle2 className="h-4 w-4 text-success" />
        )}
        <span
          className={cn(
            "text-sm font-semibold",
            color === "destructive" && "text-destructive",
            color === "warning" && "text-warning",
            color === "success" && "text-success",
          )}
        >
          {hasOverrun ? "Budget Overrun Detected" : hasWarning ? "Budget Warning" : "Within Budget"}
        </span>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">{detail}</p>
      {(remainingMatch || budgetMatch || committedMatch) && (
        <div className="flex gap-6 mt-3">
          {budgetMatch && (
            <div className="text-center">
              <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Budget</div>
              <div className="text-sm font-bold font-mono">${budgetMatch[1]}</div>
            </div>
          )}
          {committedMatch && (
            <div className="text-center">
              <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Committed</div>
              <div className="text-sm font-bold font-mono text-warning">${committedMatch[1]}</div>
            </div>
          )}
          {remainingMatch && (
            <div className="text-center">
              <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Remaining</div>
              <div className={cn("text-sm font-bold font-mono", hasOverrun ? "text-destructive" : "text-success")}>
                ${remainingMatch[1]}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- Inline agent result components ---------- */
function FindingsList({ findings }: { findings: AgentFinding[] }) {
  if (!findings || findings.length === 0) return null;
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-muted-foreground">Findings</h4>
      <div className="space-y-1.5">
        {findings.map((f, i: number) => (
          <div key={i} className="flex items-start gap-2 text-sm">
            {f.status === "PASS" ? (
              <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" />
            ) : f.status === "WARN" ? (
              <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
            ) : (
              <XCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
            )}
            <div>
              <span className="font-medium">{f.check}</span>
              {f.detail && <span className="text-muted-foreground"> -- {f.detail}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- Run History Panel ---------- */
function RunHistoryPanel({ documentId }: { documentId: string }) {
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [expandedWorkflows, setExpandedWorkflows] = useState<Set<string>>(new Set());

  useEffect(() => {
    // Defer state updates off the render commit (avoids synchronous
    // setState in effect); behavior is unchanged.
    queueMicrotask(() => {
      setLoading(true);
      setExpandedWorkflows(new Set());
      api.getDocumentRuns(documentId).then((data) => {
        const r = (data?.runs || []) as RunEntry[];
        setRuns(r);
        // Auto-expand all workflows
        const wfIds = new Set(
          r.filter((e) => e.type === "workflow").map((e) => e.id).filter((id): id is string => !!id),
        );
        setExpandedWorkflows(wfIds);
      }).catch(() => setRuns([])).finally(() => setLoading(false));
    });
  }, [documentId]);

  if (loading) return null;
  if (runs.length === 0) return null;

  const topLevel = runs.filter((r) => !r.parent_id);
  const getChildren = (parentId: string) => runs.filter((r) => r.parent_id === parentId);

  const typeLabel = (r: RunEntry) => {
    if (r.type === "workflow") return "Workflow";
    if (r.type === "decision") return "Decision";
    const labels: Record<string, string> = {
      requisition: "Requisition Analysis", sourcing: "Sourcing Evaluation",
      po_management: "PO Generation", invoice_matching: "Invoice Matching",
      payment: "Payment", receiving: "Receiving",
    };
    return (r.agent ? labels[r.agent] : undefined) || r.agent || "Analysis";
  };

  const statusVariant = (s?: string) => {
    if (s === "completed" || s === "approved") return "approved";
    if (s === "rejected" || s === "failed") return "rejected";
    return "warning";
  };

  return (
    <div className="rounded-lg border">
      <button
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <span>Run History for {documentId} ({topLevel.length})</span>
        {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>
      {expanded && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8"></TableHead>
              <TableHead>ID</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Recommendation</TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead>Time</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {topLevel.map((run) => {
              const runId = run.id || "";
              const isWorkflow = run.type === "workflow";
              const isExpanded = expandedWorkflows.has(runId);
              const children = isWorkflow ? getChildren(runId) : [];
              return (
                <React.Fragment key={runId}>
                  <TableRow className={isWorkflow ? "bg-muted/30" : ""}>
                    <TableCell>
                      {isWorkflow && children.length > 0 ? (
                        <button
                          className="p-0.5"
                          onClick={() => {
                            const next = new Set(expandedWorkflows);
                            if (isExpanded) next.delete(runId);
                            else next.add(runId);
                            setExpandedWorkflows(next);
                          }}
                        >
                          {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                        </button>
                      ) : null}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{run.id?.substring(0, 8)}</TableCell>
                    <TableCell className="text-xs font-medium">{typeLabel(run)}</TableCell>
                    <TableCell><StatusBadge status={statusVariant(run.status)}>{run.status?.replace(/_/g, " ")}</StatusBadge></TableCell>
                    <TableCell className="text-xs">{run.action || run.recommendation || "--"}</TableCell>
                    <TableCell className="text-xs">{run.confidence ? `${Math.round(Number(run.confidence) * 100)}%` : "--"}</TableCell>
                    <TableCell className="text-xs whitespace-nowrap">{(run.started_at || "").substring(0, 19).replace("T", " ")}</TableCell>
                  </TableRow>
                  {isExpanded && children.map((child) => (
                    <TableRow key={child.id} className="bg-muted/10">
                      <TableCell><span className="inline-block w-3 ml-2 border-l border-b border-muted-foreground/30 h-3" /></TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{child.id?.substring(0, 8)}</TableCell>
                      <TableCell className="text-xs">{typeLabel(child)}</TableCell>
                      <TableCell><StatusBadge status={statusVariant(child.status)}>{child.status?.replace(/_/g, " ")}</StatusBadge></TableCell>
                      <TableCell className="text-xs">{child.action || child.recommendation || "--"}</TableCell>
                      <TableCell className="text-xs">{child.confidence ? `${Math.round(Number(child.confidence) * 100)}%` : "--"}</TableCell>
                      <TableCell className="text-xs whitespace-nowrap">{(child.started_at || "").substring(0, 19).replace("T", " ")}</TableCell>
                    </TableRow>
                  ))}
                </React.Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

export default function Requisitions() {
  const { user } = useAuth();
  const role = resolveRole(user?.role);
  const isRequester = role === "requester";

  const [allItems, setAllItems] = useState<Requisition[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedItem, setSelectedItem] = useState<Requisition | null>(null);
  const [agentResult, setAgentResult] = useState<AgentResult | null>(null);
  // meta is captured for parity with prior behavior but not rendered here.
  const [, setAgentMeta] = useState<ReturnType<typeof useAgentStream>["meta"]>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [runningWorkflow, setRunningWorkflow] = useState(false);
  const [rejectedWorkflow, setRejectedWorkflow] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [activeTab, setActiveTab] = useState("all");
  const [filterText, setFilterText] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [expandedLineItems, setExpandedLineItems] = useState(true);
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkApproving, setBulkApproving] = useState(false);
  const [runHistory, setRunHistory] = useState<RunEntry[]>([]);
  const [runHistoryExpanded, setRunHistoryExpanded] = useState(true);
  const PAGE_SIZE = 20;

  const agent = useAgentStream();

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await erpApi.listRequisitions();
      let items = data.requisitions || [];
      // Requesters only see their own PRs
      if (isRequester && user?.email) {
        items = items.filter((r) => r.requester === user.email);
      }
      setAllItems(items);
    } catch (e) {
      console.error("Failed to load requisitions:", e);
    }
    setLoading(false);
  };

  // Defer the initial load off the render commit so fetchData's loader
  // setState doesn't run synchronously inside the effect.
  useEffect(() => { queueMicrotask(fetchData); }, []);

  // Categorize by canonical lowercase status (adapter-normalized)
  const pending = allItems.filter((r) => r.status === "pending_approval" || r.status === "submitted");
  const ordered = allItems.filter((r) => r.status === "ordered" || r.status === "approved");
  const draft = allItems.filter((r) => r.status === "draft");
  const cancelled = allItems.filter((r) => r.status === "cancelled");

  const getTabItems = (): Requisition[] => {
    switch (activeTab) {
      case "pending": return pending;
      case "ordered": return ordered;
      case "draft": return draft;
      case "cancelled": return cancelled;
      case "all": return allItems;
      default: return allItems;
    }
  };

  /* ---------- Agent invocation: Analyze ---------- */
  const analyzeSelected = async () => {
    if (!selectedItem) return;
    setAnalyzing(true);
    setShowModal(true);
    setRejectedWorkflow(false);
    setAgentResult(null);
    setAgentMeta(null);
    setRunHistory([]);
    setRunHistoryExpanded(true);
    agent.reset();
    // Fetch run history
    api.getDocumentRuns(selectedItem.requisition_id).then((data) => {
      setRunHistory((data?.runs || []) as RunEntry[]);
    }).catch(() => { /* run history is non-critical */ });
    try {
      await agent.invoke("requisition", selectedItem.requisition_id);
    } catch {
      // Error is captured in agent.error
    }
  };

  // Sync agent hook state -> component state when agent finishes.
  const prevAgentResult = useRef<unknown>(null);
  useEffect(() => {
    if (agent.result && agent.result !== prevAgentResult.current) {
      prevAgentResult.current = agent.result;
      const result = agent.result as AgentResult;
      const meta = agent.meta;
      // Defer off the render commit (avoids synchronous setState in effect).
      queueMicrotask(() => {
        setAgentResult(result);
        setAgentMeta(meta);
        setAnalyzing(false);
      });
    }
    if (agent.error && analyzing) {
      const err = agent.error;
      queueMicrotask(() => {
        setAgentResult({ error: err });
        setAnalyzing(false);
      });
    }
  }, [agent.result, agent.error, analyzing]);

  /* ---------- Agent invocation: Workflow ---------- */
  const runFullWorkflow = async () => {
    if (!selectedItem) return;
    setShowModal(true);
    setRejectedWorkflow(false);
    setAgentResult(null);
    setAgentMeta(null);
    setRunHistory([]);
    setRunHistoryExpanded(true);

    // Fetch run history for this MR
    api.getDocumentRuns(selectedItem.requisition_id).then((data) => {
      setRunHistory((data?.runs || []) as RunEntry[]);
    }).catch(() => { /* run history is non-critical */ });

    // Check if there's an existing lifecycle record (e.g., PENDING_APPROVAL from a previous run)
    try {
      const lc = await api.getLifecycle(selectedItem.requisition_id);

      // Helper: extract step data from runs[] array
      const runs: RunEntry[] = typeof lc?.runs === "string" ? JSON.parse(lc.runs || "[]") : ((lc?.runs as RunEntry[]) || []);
      const latestWorkflow = [...runs].reverse().find((r) => r.type === "workflow");
      const wfChildren = latestWorkflow ? runs.filter((r) => r.parent_id === latestWorkflow.id) : [];
      const reqStep = wfChildren.find((r) => r.agent === "requisition");
      const srcStep = wfChildren.find((r) => r.agent === "sourcing");
      const poStep = wfChildren.find((r) => r.agent === "po_management");
      const reqResult = (reqStep?.result || {}) as {
        recommendation?: string; risk_level?: string; confidence?: number;
        reasoning?: string; findings?: AgentFinding[]; auto_approved?: boolean;
      };
      const srcResult = (srcStep?.result || {}) as {
        vendor_name?: string; vendor_score?: number; reasoning?: string;
      };

      // Check for actively running workflow — prevent duplicate invocation
      const RUNNING_STATES = ["CREATED", "SOURCING", "SOURCING_COMPLETE", "ANALYZING", "PO_GENERATION"];
      if (lc?.status && RUNNING_STATES.includes(lc.status)) {
        setAgentResult({
          workflow: true,
          workflow_status: "RUNNING",
          current_step: lc.current_step || lc.status,
          reasoning: `A workflow is already running (step: ${lc.current_step || lc.status}). Please wait for it to complete, then refresh to see the result.`,
          recommendation: reqResult?.recommendation || "",
          risk_level: reqResult?.risk_level || "",
          confidence: reqResult?.confidence || 0,
          findings: reqResult?.findings || [],
          auto_approved: false,
          sourcing_result: srcResult?.vendor_name ? {
            recommended_vendor: { supplier_name: srcResult.vendor_name, score: srcResult.vendor_score },
            reasoning: srcResult.reasoning || srcStep?.summary || "",
          } : null,
        });
        return;
      }

      if (lc?.status === "PENDING_APPROVAL" && reqStep) {
        // Restore both analysis AND sourcing from runs[] — no top-level duplication
        const findings = reqResult.findings || [];
        setAgentResult({
          recommendation: reqResult.recommendation || reqStep.recommendation || "",
          risk_level: reqResult.risk_level || "",
          confidence: reqResult.confidence || Number(reqStep.confidence) || 0,
          reasoning: reqResult.reasoning || reqStep.summary || "",
          findings,
          auto_approved: false,
          workflow: true,
          workflow_status: "PENDING_APPROVAL",
          sourcing_result: srcResult.vendor_name ? {
            recommended_vendor: { supplier_name: srcResult.vendor_name, score: srcResult.vendor_score },
            reasoning: srcResult.reasoning || srcStep?.summary || "",
          } : null,
        });
        return;
      }
      if (lc?.status === "PO_CREATED" && reqStep) {
        const poResult = (poStep?.result || {}) as { created_order_id?: string };
        setAgentResult({
          workflow: true,
          workflow_status: "COMPLETE",
          created_order_id: poResult.created_order_id || lc.po_order_id || "",
          recommendation: reqResult.recommendation || "APPROVE",
          risk_level: reqResult.risk_level || "",
          confidence: reqResult.confidence || 0,
          reasoning: "Workflow previously completed.",
          findings: reqResult.findings || [],
          auto_approved: !!reqResult.auto_approved,
          sourcing_result: srcResult.vendor_name ? {
            recommended_vendor: { supplier_name: srcResult.vendor_name, score: srcResult.vendor_score },
            reasoning: srcResult.reasoning || "",
          } : null,
        });
        return;
      }
      if (lc?.status === "REJECTED") {
        setAgentResult({
          workflow: true,
          workflow_status: "REJECTED",
          recommendation: reqResult.recommendation || "",
          risk_level: reqResult.risk_level || "",
          confidence: 0,
          reasoning: `Rejected by ${lc.rejected_by || "unknown"}`,
          findings: reqResult.findings || [],
        });
        return;
      }
    } catch { /* lifecycle fetch failed — proceed fresh */ }

    // No existing lifecycle or in a restartable state — invoke fresh
    setRunningWorkflow(true);
    agent.reset();
    try {
      await agent.invoke("workflow", selectedItem.requisition_id);
    } catch {
      // Error captured in agent.error
    }
  };

  // Sync workflow results from agent hook
  const prevWorkflowResult = useRef<unknown>(null);
  useEffect(() => {
    if (!runningWorkflow) return;
    if (agent.result && agent.result !== prevWorkflowResult.current) {
      prevWorkflowResult.current = agent.result;
      const result = agent.result as RawWorkflowResult;
      const meta = agent.meta;

      const steps = result.steps || [];
      const srcStep = steps.find((s) => s.agent === "sourcing");
      const poStep = steps.find((s) => s.agent === "po_management");

      const normalized: AgentResult = {
        recommendation: result.recommendation || result.status || "",
        risk_level: result.risk_level || "",
        confidence: result.confidence || 0,
        reasoning: result.reasoning || result.message || result.error || "",
        findings: result.findings || [],
        auto_approved: result.auto_approved || false,
        workflow: true,
        workflow_status: result.workflow_status || result.status,
        workflow_steps: steps,
        sourcing_result: result.sourcing_result || (srcStep?.result || result.recommended_vendor ? { recommended_vendor: result.recommended_vendor, ...srcStep?.result } : null),
        po_result: result.po_result || poStep?.result || null,
        created_order_id: result.created_order_id || "",
        erp_action_taken: result.erp_action_taken || "",
      };
      // Defer off the render commit (avoids synchronous setState in effect).
      queueMicrotask(() => {
        setAgentMeta(meta);
        setAgentResult(normalized);
        setRunningWorkflow(false);
      });
    }
    if (agent.error && runningWorkflow) {
      const err = agent.error;
      queueMicrotask(() => {
        setAgentResult({ error: err });
        setRunningWorkflow(false);
      });
    }
  }, [agent.result, agent.error, runningWorkflow]);

  /* ---------- Derived data ---------- */
  const tabItems = getTabItems();
  const filtered = filterText
    ? tabItems.filter((r) =>
        [r.requisition_id, r.status, r.requester, r.purpose]
          .filter(Boolean)
          .some((v) => v!.toLowerCase().includes(filterText.toLowerCase()))
      )
    : tabItems;
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginatedItems = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const showActions = !isRequester && selectedItem;

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Purchase Requisitions</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isRequester ? "Track your purchase requisitions" : "Review and manage purchase requisitions"}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={(v) => { setActiveTab(v); setSelectedItem(null); setCurrentPage(1); }}>
        <TabsList>
          <TabsTrigger value="all">All ({allItems.length})</TabsTrigger>
          <TabsTrigger value="pending">Pending ({pending.length})</TabsTrigger>
          <TabsTrigger value="ordered">Ordered ({ordered.length})</TabsTrigger>
          <TabsTrigger value="draft">Draft ({draft.length})</TabsTrigger>
          <TabsTrigger value="cancelled">Cancelled ({cancelled.length})</TabsTrigger>
        </TabsList>

        {/* Shared content for all tabs */}
        <TabsContent value={activeTab} forceMount className="mt-4 space-y-4">
          {/* Toolbar: search + agent actions */}
          <div className="flex items-center justify-between gap-4">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by ID, requester, or status"
                value={filterText}
                onChange={(e) => { setFilterText(e.target.value); setCurrentPage(1); }}
                className="pl-9"
              />
            </div>
            {showActions && (
              <div className="flex gap-2">
                {selectedIds.size >= 2 && (
                  <Button
                    variant="outline"
                    size="sm"
                    loading={bulkApproving}
                    onClick={async () => {
                      setBulkApproving(true);
                      try {
                        await Promise.all(
                          Array.from(selectedIds).map((id) =>
                            api.recordDecision({ document_type: "PR", document_id: id, action: "APPROVE", justification: "Bulk approved" })
                          )
                        );
                        setSelectedIds(new Set());
                        fetchData();
                      } catch (e) { console.error(e); }
                      setBulkApproving(false);
                    }}
                  >
                    Bulk Approve ({selectedIds.size})
                  </Button>
                )}
                <Button variant="outline" size="sm" disabled={!selectedItem || selectedItem.status === "ordered"} onClick={runFullWorkflow} loading={runningWorkflow} title="Runs 3 agents in sequence: Requisition Analysis → Supplier Sourcing → PO Generation. Fully automated end-to-end.">
                  Run Full Workflow
                </Button>
                <Button size="sm" disabled={!selectedItem || selectedItem.status === "ordered"} onClick={analyzeSelected} loading={analyzing} title="Runs the Requisition Agent to analyze risk, pricing, duplicates, and budget. You approve/reject the findings.">
                  Analyze with Agent
                </Button>
              </div>
            )}
          </div>

          {/* Data Table */}
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : paginatedItems.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No requisitions found</div>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    {showActions && (
                      <TableHead className="w-10">
                        <input
                          type="checkbox"
                          className="rounded border-border"
                          checked={paginatedItems.length > 0 && paginatedItems.every((i) => selectedIds.has(i.requisition_id))}
                          onChange={(e) => {
                            const next = new Set(selectedIds);
                            paginatedItems.forEach((i) => e.target.checked ? next.add(i.requisition_id) : next.delete(i.requisition_id));
                            setSelectedIds(next);
                          }}
                        />
                      </TableHead>
                    )}
                    <TableHead>Requisition ID</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Requester</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Total Amount</TableHead>
                    <TableHead className="text-right">Line Items</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {paginatedItems.map((item) => (
                    <TableRow
                      key={item.requisition_id}
                      className={cn(
                        "cursor-pointer",
                        selectedItem?.requisition_id === item.requisition_id && "bg-muted",
                      )}
                      onClick={() => {
                        if (isRequester) {
                          setSelectedItem(item);
                          setShowDetailModal(true);
                        } else {
                          setSelectedItem(selectedItem?.requisition_id === item.requisition_id ? null : item);
                        }
                      }}
                    >
                      {showActions && (
                        <TableCell>
                          <input
                            type="checkbox"
                            className="rounded border-border"
                            checked={selectedIds.has(item.requisition_id)}
                            onClick={(e) => e.stopPropagation()}
                            onChange={() => {
                              const next = new Set(selectedIds);
                              if (next.has(item.requisition_id)) next.delete(item.requisition_id);
                              else next.add(item.requisition_id);
                              setSelectedIds(next);
                            }}
                          />
                        </TableCell>
                      )}
                      <TableCell className="font-medium">{item.requisition_id}</TableCell>
                      <TableCell><StatusBadge status={item.status || "unknown"} /></TableCell>
                      <TableCell>{item.requester || "--"}</TableCell>
                      <TableCell>{item.created_date || "--"}</TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(item.total_amount)}</TableCell>
                      <TableCell className="text-right text-xs max-w-[250px]">
                        {item.line_items && item.line_items.length > 0
                          ? item.line_items.map((li, idx: number) => (
                              <div key={idx} className="truncate">
                                <span className="font-mono text-blue-600 dark:text-blue-400">{li.item_id}</span>
                                {" "}
                                <span className="text-muted-foreground">x{li.quantity}</span>
                                {li.unit_price ? <span className="ml-1 font-mono">${li.unit_price.toFixed(2)}</span> : null}
                              </div>
                            ))
                          : <span className="text-muted-foreground">--</span>
                        }
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {/* Pagination */}
          {filtered.length > PAGE_SIZE && (
            <div className="flex items-center justify-between px-1">
              <p className="text-sm text-muted-foreground">
                Page {currentPage} of {totalPages} ({filtered.length} total)
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={currentPage <= 1} onClick={() => setCurrentPage((p) => p - 1)}>
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={currentPage >= totalPages} onClick={() => setCurrentPage((p) => p + 1)}>
                  Next
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Line items detail for selected requisition (non-requester) */}
      {selectedItem && selectedItem.line_items && selectedItem.line_items.length > 0 && !isRequester && (
        <div className="rounded-lg border">
          <button
            className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50 transition-colors"
            onClick={() => setExpandedLineItems(!expandedLineItems)}
          >
            <span>Line Items for {selectedItem.requisition_id} ({selectedItem.line_items.length})</span>
            {expandedLineItems ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {expandedLineItems && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item ID</TableHead>
                  <TableHead>Item Name</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Unit Price</TableHead>
                  <TableHead>Delivery Date</TableHead>
                  <TableHead>Warehouse</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {selectedItem.line_items.map((li: RequisitionLineItem, idx: number) => (
                  <TableRow key={idx}>
                    <TableCell>{li.item_id}</TableCell>
                    <TableCell>{li.item_name || "--"}</TableCell>
                    <TableCell className="text-right">{li.quantity}</TableCell>
                    <TableCell className="text-right font-mono">{li.unit_price != null ? formatCurrency(li.unit_price) : "--"}</TableCell>
                    <TableCell>{li.delivery_date || "--"}</TableCell>
                    <TableCell>{li.warehouse || "--"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      )}

      {/* Run History Panel — shows below MR when selected */}
      {selectedItem && !isRequester && <RunHistoryPanel documentId={selectedItem.requisition_id} />}

      {/* Agent Analysis Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>
              {rejectedWorkflow
                ? "ARIA Workflow -- Rejected"
                : runningWorkflow || agentResult?.workflow
                ? "ARIA Workflow -- Multi-Agent Chain"
                : "Requisition Agent Analysis"}
            </DialogTitle>
          </DialogHeader>

          {rejectedWorkflow ? (
            <div className="space-y-4 py-4">
              <AgentStepList steps={deriveRejectionSteps()} isRunning={false} />
              <div className="flex justify-end pt-2 border-t">
                <Button variant="ghost" size="sm" onClick={() => { setShowModal(false); setRejectedWorkflow(false); }}>Close</Button>
              </div>
            </div>
          ) : (analyzing || runningWorkflow) ? (
            <div className="py-4">
              {runningWorkflow ? (
                <AgentStepList steps={deriveWorkflowSteps(agent.progress)} progress={agent.progress} isRunning={runningWorkflow} />
              ) : (
                <AgentStepList progress={agent.progress} isRunning={analyzing} title="Requisition Agent" />
              )}
            </div>
          ) : agentResult ? (
            <div className="space-y-5">
              {/* Recommendation / Risk / Confidence */}
              {agentResult.recommendation && (
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Recommendation</p>
                    <StatusBadge status={agentResult.recommendation === "APPROVE" ? "approved" : agentResult.recommendation === "REJECT" ? "rejected" : "warning"}>
                      {agentResult.recommendation}
                    </StatusBadge>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Risk Level</p>
                    <span className="text-sm font-medium">{agentResult.risk_level || "--"}</span>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Confidence</p>
                    <span className="text-sm font-medium">{((agentResult.confidence || 0) * 100).toFixed(0)}%</span>
                  </div>
                </div>
              )}

              {/* Reasoning */}
              {agentResult.reasoning && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Reasoning</p>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{agentResult.reasoning}</p>
                </div>
              )}

              {/* Budget Impact */}
              {agentResult.findings && agentResult.findings.some((f) => f.check?.toLowerCase().includes("budget")) && (
                <BudgetImpactIndicator findings={agentResult.findings} />
              )}

              {/* Findings */}
              {agentResult.findings && agentResult.findings.length > 0 && (
                <FindingsList findings={agentResult.findings} />
              )}

              {/* Workflow step 2: Sourcing */}
              {agentResult.workflow && agentResult.sourcing_result && (
                <div className="space-y-2 border-t pt-4">
                  <h3 className="text-sm font-semibold">Step 2: Vendor Sourcing</h3>
                  {agentResult.sourcing_result.recommended_vendor && (
                    <div className="flex items-center gap-2 text-sm">
                      <CheckCircle2 className="h-4 w-4 text-success" />
                      <span>
                        Recommended: {agentResult.sourcing_result.recommended_vendor.supplier_name || agentResult.sourcing_result.recommended_vendor.supplier_id}
                        {agentResult.sourcing_result.recommended_vendor.score ? ` (Score: ${agentResult.sourcing_result.recommended_vendor.score}/100)` : ""}
                      </span>
                    </div>
                  )}
                  {agentResult.sourcing_result.reasoning && (
                    <p className="text-sm text-muted-foreground whitespace-pre-wrap">{agentResult.sourcing_result.reasoning}</p>
                  )}
                </div>
              )}

              {/* Workflow step 3: PO Generation */}
              {agentResult.workflow && agentResult.po_result && (
                <div className="space-y-2 border-t pt-4">
                  <h3 className="text-sm font-semibold">Step 3: PO Generation</h3>
                  <div className="flex items-center gap-2 text-sm">
                    <StatusBadge status={agentResult.po_result.action === "CREATE" ? "completed" : "submitted"}>
                      {agentResult.po_result.action || "Draft ready"}
                    </StatusBadge>
                  </div>
                  {agentResult.po_result.reasoning && (
                    <p className="text-sm text-muted-foreground whitespace-pre-wrap">{agentResult.po_result.reasoning}</p>
                  )}
                </div>
              )}

              {/* Workflow Status */}
              {agentResult.workflow && (
                <div className="border-t pt-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Workflow Status</p>
                  <div className="flex items-center gap-2">
                    {agentResult.workflow_status === "RUNNING" && <Spinner size="sm" />}
                    <StatusBadge status={agentResult.workflow_status === "COMPLETE" ? "completed" : agentResult.workflow_status === "RUNNING" ? "submitted" : "warning"}>
                      {agentResult.workflow_status === "RUNNING" ? "In Progress" : agentResult.workflow_status}
                    </StatusBadge>
                  </div>
                </div>
              )}

              {/* Error */}
              {agentResult.error && (
                <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
                  {agentResult.error}
                </div>
              )}

              {/* Run History Tree */}
              {runHistory.length > 0 && (
                <div className="border-t pt-4">
                  <button
                    className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider hover:text-foreground"
                    onClick={() => setRunHistoryExpanded(!runHistoryExpanded)}
                  >
                    {runHistoryExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    Run History ({runHistory.filter((r) => !r.parent_id).length})
                  </button>
                  {runHistoryExpanded && (
                    <div className="mt-2 space-y-1 text-xs">
                      {runHistory.filter((r) => !r.parent_id).map((run) => {
                        const children = runHistory.filter((r) => r.parent_id === run.id);
                        const isWorkflow = run.type === "workflow";
                        return (
                          <div key={run.id} className="rounded border bg-muted/20 p-2">
                            <div className="flex items-center gap-2">
                              <StatusBadge status={run.status === "completed" || run.status === "approved" ? "approved" : run.status === "rejected" || run.status === "failed" ? "rejected" : "warning"}>
                                {run.status?.replace(/_/g, " ")}
                              </StatusBadge>
                              <span className="font-medium">{isWorkflow ? "Workflow" : (run.agent || run.type)}</span>
                              <span className="text-muted-foreground ml-auto">{(run.started_at || "").substring(0, 19).replace("T", " ")}</span>
                            </div>
                            {children.length > 0 && (
                              <div className="mt-1.5 ml-4 space-y-1 border-l pl-3">
                                {children.map((child) => (
                                  <div key={child.id} className="flex items-center gap-2 text-muted-foreground">
                                    <span className="font-medium text-foreground">
                                      {child.type === "decision" ? "Decision" : (child.agent || child.type)}
                                    </span>
                                    {child.action && (
                                      <StatusBadge status={(child.action || "").includes("APPROVED") ? "approved" : (child.action || "").includes("REJECTED") ? "rejected" : "warning"}>
                                        {child.action}
                                      </StatusBadge>
                                    )}
                                    {child.recommendation && !child.action && (
                                      <span>{child.recommendation}</span>
                                    )}
                                    {child.confidence ? <span>({Math.round(Number(child.confidence) * 100)}%)</span> : null}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Footer actions — Analysis is read-only preview */}
              {!agentResult.error && !agentResult.workflow && (
                <div className="space-y-3 pt-2 border-t">
                  <p className="text-xs text-muted-foreground">This is a read-only preview. Use "Run Full Workflow" to take action.</p>
                  <div className="flex justify-between items-center">
                    <Button variant="ghost" size="sm" onClick={() => setShowModal(false)}>Close</Button>
                    <Button size="sm" onClick={() => { setShowModal(false); runFullWorkflow(); }}>
                      Run Full Workflow
                    </Button>
                  </div>
                </div>
              )}

              {/* Workflow footer — approve/reject for PENDING_APPROVAL, or show PO created */}
              {!agentResult.error && agentResult.workflow && (
                <div className="space-y-3 pt-2 border-t">
                  {agentResult.workflow_status === "COMPLETE" && agentResult.created_order_id && (
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-5 w-5 text-green-500" />
                      <span className="text-sm font-medium">Purchase Order {agentResult.created_order_id} created in ERP</span>
                      {agentResult.auto_approved && <StatusBadge status="approved">Auto-Approved</StatusBadge>}
                    </div>
                  )}
                  {agentResult.workflow_status === "COMPLETE" && !agentResult.created_order_id && (
                    <div className="flex items-center gap-2">
                      <StatusBadge status="completed">Workflow Complete</StatusBadge>
                    </div>
                  )}
                  {agentResult.workflow_status === "PENDING_APPROVAL" && (
                    <>
                      <p className="text-sm font-medium text-amber-600 dark:text-amber-400">Analysis and sourcing are complete. Review the findings above and approve or reject.</p>
                      <Input
                        placeholder="Justification (optional)..."
                        value={justification}
                        onChange={(e) => setJustification(e.target.value)}
                      />
                      <div className="flex justify-between gap-2">
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={submitting}
                          onClick={async () => {
                            setSubmitting(true);
                            try {
                              await api.recordDecision({
                                document_type: "PR",
                                document_id: selectedItem?.requisition_id || "",
                                action: "REJECT",
                                justification,
                                agent_recommendation: agentResult.recommendation,
                                agent_confidence: agentResult.confidence,
                                agent_reasoning: agentResult.reasoning,
                              });
                              setJustification("");
                              setRejectedWorkflow(true);
                              setAgentResult(null);
                              fetchData();
                            } catch (e) { console.error(e); }
                            setSubmitting(false);
                          }}
                        >
                          Reject
                        </Button>
                        <Button
                          size="sm"
                          disabled={submitting}
                          onClick={async () => {
                            setSubmitting(true);
                            try {
                              // Record the human approval decision
                              await api.recordDecision({
                                document_type: "PR",
                                document_id: selectedItem?.requisition_id || "",
                                action: "APPROVE",
                                justification,
                                agent_recommendation: agentResult.recommendation,
                                agent_confidence: agentResult.confidence,
                                agent_reasoning: agentResult.reasoning,
                              });
                              // Resume the workflow from PO generation (Steps 1+2 already done)
                              setJustification("");
                              setRunningWorkflow(true);
                              setAgentResult(null);
                              agent.reset();
                              await agent.invoke("workflow", selectedItem?.requisition_id || "", { resume_from: "po_generation" });
                            } catch (e) { console.error(e); }
                            setSubmitting(false);
                          }}
                        >
                          {submitting ? "Processing..." : "Approve & Generate PO"}
                        </Button>
                      </div>
                    </>
                  )}
                  {agentResult.workflow_status === "RUNNING" && (
                    <div className="flex items-center gap-2">
                      <Spinner size="sm" />
                      <span className="text-sm text-muted-foreground">
                        Workflow in progress (step: {agentResult.current_step || "running"})
                      </span>
                      <Button variant="ghost" size="sm" onClick={() => setShowModal(false)}>Close</Button>
                    </div>
                  )}
                  {agentResult.workflow_status && !["COMPLETE", "PENDING_APPROVAL", "RUNNING"].includes(agentResult.workflow_status) && (
                    <div className="flex items-center gap-2">
                      <StatusBadge status="warning">{agentResult.workflow_status}</StatusBadge>
                      <Button variant="ghost" size="sm" onClick={() => setShowModal(false)}>Close</Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      {/* Detail Modal (read-only view for requesters) */}
      <Dialog open={showDetailModal} onOpenChange={setShowDetailModal}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>Requisition {selectedItem?.requisition_id} -- Details</DialogTitle>
          </DialogHeader>
          {selectedItem && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Status</p>
                  <StatusBadge status={selectedItem.status || "unknown"} />
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Requester</p>
                  <p className="text-sm">{selectedItem.requester || "--"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Created Date</p>
                  <p className="text-sm">{selectedItem.created_date || "--"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Total Amount</p>
                  <p className="text-sm font-mono">{formatCurrency(selectedItem.total_amount)}</p>
                </div>
                {selectedItem.purpose && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Purpose</p>
                    <p className="text-sm">{selectedItem.purpose}</p>
                  </div>
                )}
                {selectedItem.department && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Department</p>
                    <p className="text-sm">{selectedItem.department}</p>
                  </div>
                )}
              </div>

              {selectedItem.line_items && selectedItem.line_items.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                    Line Items ({selectedItem.line_items.length})
                  </p>
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Item ID</TableHead>
                          <TableHead>Item Name</TableHead>
                          <TableHead className="text-right">Qty</TableHead>
                          <TableHead className="text-right">Unit Price</TableHead>
                          <TableHead>Delivery Date</TableHead>
                          <TableHead>Warehouse</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {selectedItem.line_items.map((li, idx) => (
                          <TableRow key={idx}>
                            <TableCell>{li.item_id}</TableCell>
                            <TableCell>{li.item_name || "--"}</TableCell>
                            <TableCell className="text-right">{li.quantity}</TableCell>
                            <TableCell className="text-right font-mono">{li.unit_price != null ? formatCurrency(li.unit_price) : "--"}</TableCell>
                            <TableCell>{li.delivery_date || "--"}</TableCell>
                            <TableCell>{li.warehouse || "--"}</TableCell>
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

/* Old RejectionStepper and WorkflowStepper replaced by AgentStepList + deriveWorkflowSteps/deriveRejectionSteps */
