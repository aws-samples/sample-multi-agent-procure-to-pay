// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import {
  Search,
  ChevronDown, ChevronRight as ChevronRightIcon,
  GitBranch, Microscope, CheckSquare, FileText,
} from "lucide-react";
import { api } from "../api";
import { resolveUserName } from "../lookups";
import AgentReasoning from "../components/AgentReasoning";
import { useTranslation } from "react-i18next";

interface RunEntry {
  id?: string;
  decision_id: string;
  document_type: string;
  document_id: string;
  type: string;
  agent: string;
  action: string;
  status: string;
  decided_by: string;
  decided_at: string;
  recommendation: string;
  confidence: number;
  summary: string;
  justification: string;
  parent_id: string;
  agent_recommendation: string;
  agent_confidence: string;
  agent_reasoning: string;
}

interface MRGroup {
  document_id: string;
  entries: RunEntry[];
  latestTime: string;
}

function statusBadge(status: string, t: (key: string) => string) {
  if (!status) return null;
  const normalized = status.toLowerCase();
  if (normalized === "completed" || normalized === "approved")
    return <StatusBadge status="approved">{status.replace(/_/g, " ")}</StatusBadge>;
  if (normalized === "rejected" || normalized === "failed")
    return <StatusBadge status="rejected">{status.replace(/_/g, " ")}</StatusBadge>;
  if (normalized === "pending_approval")
    return <StatusBadge status="warning">{t("decisions.ui.pendingApproval")}</StatusBadge>;
  if (normalized === "running")
    return <StatusBadge status="info">{t("decisions.ui.running")}</StatusBadge>;
  return <StatusBadge status="warning">{status.replace(/_/g, " ")}</StatusBadge>;
}

function typeIcon(type: string, agent: string) {
  if (type === "workflow") return <GitBranch className="h-4 w-4 text-blue-500" />;
  if (type === "decision") return <CheckSquare className="h-4 w-4 text-amber-500" />;
  if (agent === "receiving" || agent === "invoice_matching" || agent === "payment")
    return <FileText className="h-4 w-4 text-green-500" />;
  return <Microscope className="h-4 w-4 text-purple-500" />;
}

function typeLabel(entry: RunEntry) {
  if (entry.type === "workflow") {
    if (entry.agent === "payment_workflow") return "Payment Workflow";
    return "Workflow";
  }
  if (entry.type === "decision") {
    if (entry.action === "PAYMENT_SCHEDULED") return "Payment Scheduled";
    return "Decision";
  }
  const labels: Record<string, string> = {
    requisition: "Requisition Analysis",
    sourcing: "Sourcing Evaluation",
    po_management: "PO Generation",
    invoice_matching: "Invoice 3-Way Match",
    payment: "Payment Analysis",
    receiving: "Receiving Validation",
  };
  return labels[entry.agent] || entry.agent || entry.type;
}

function decidedByLabel(entry: RunEntry) {
  if (!entry.decided_by) {
    if (entry.type === "workflow" || entry.type === "analysis") return "AI Agent";
    return "--";
  }
  if (entry.decided_by === "AI_AGENT") return "AI Agent";
  if (entry.decided_by === "AI_AGENT_PENDING") return "Pending Review";
  return resolveUserName(entry.decided_by);
}

export default function Decisions() {
  const { t } = useTranslation();
  const [items, setItems] = useState<RunEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [selectedItem, setSelectedItem] = useState<RunEntry | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [expandedMRs, setExpandedMRs] = useState<Set<string>>(new Set());
  const [expandedWorkflows, setExpandedWorkflows] = useState<Set<string>>(new Set());
  const [childrenCache, setChildrenCache] = useState<Record<string, RunEntry[]>>({});
  const [loadingChildren, setLoadingChildren] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.getDecisions().then((data) => {
      setItems(data || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  // Group entries by document_id (MR), sorted by most recent activity
  const topLevel = items.filter((i) => !i.parent_id);

  const groupsByMR: Record<string, RunEntry[]> = {};
  for (const entry of topLevel) {
    const key = entry.document_id;
    if (!groupsByMR[key]) groupsByMR[key] = [];
    groupsByMR[key].push(entry);
  }

  // Sort entries within each group by time ascending (oldest first — chronological)
  const mrGroups: MRGroup[] = Object.entries(groupsByMR).map(([doc_id, entries]) => {
    entries.sort((a, b) => (a.decided_at || "").localeCompare(b.decided_at || ""));
    const latest = [...entries].sort((a, b) => (b.decided_at || "").localeCompare(a.decided_at || ""))[0];
    return {
      document_id: doc_id,
      entries,
      latestTime: latest?.decided_at || "",
    };
  });

  // Sort MR groups by most recent activity (newest MR group first)
  mrGroups.sort((a, b) => b.latestTime.localeCompare(a.latestTime));

  // Filter
  const filteredGroups = filterText
    ? mrGroups.filter((g) =>
        g.document_id.toLowerCase().includes(filterText.toLowerCase()) ||
        g.entries.some((e) =>
          [e.agent, e.action, e.decided_by, e.type]
            .filter(Boolean)
            .some((v) => v.toLowerCase().includes(filterText.toLowerCase()))
        )
      )
    : mrGroups;

  const totalEntries = filteredGroups.reduce((s, g) => s + g.entries.length, 0);

  // Auto-expand all MRs on load
  useEffect(() => {
    if (mrGroups.length > 0 && expandedMRs.size === 0) {
      setExpandedMRs(new Set(mrGroups.map((g) => g.document_id)));
    }
  }, [mrGroups.length]);

  const toggleMR = (docId: string) => {
    setExpandedMRs((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
  };

  const toggleWorkflow = async (entry: RunEntry) => {
    const key = entry.decision_id;
    if (expandedWorkflows.has(key)) {
      setExpandedWorkflows((prev) => { const n = new Set(prev); n.delete(key); return n; });
      return;
    }

    // Fetch children if not cached
    if (!childrenCache[entry.document_id]) {
      setLoadingChildren((prev) => new Set(prev).add(key));
      try {
        const data = await api.getDocumentRuns(entry.document_id);
        const runs = (data?.runs || []) as RunEntry[];
        setChildrenCache((prev) => ({ ...prev, [entry.document_id]: runs }));
      } catch {
        setChildrenCache((prev) => ({ ...prev, [entry.document_id]: [] }));
      }
      setLoadingChildren((prev) => { const n = new Set(prev); n.delete(key); return n; });
    }

    setExpandedWorkflows((prev) => new Set(prev).add(key));
  };

  const getWorkflowChildren = (entry: RunEntry): RunEntry[] => {
    const allRuns = childrenCache[entry.document_id] || [];
    return allRuns.filter((r) => r.parent_id === entry.decision_id);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="animate-in space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t("decisions.ui.title")} <span className="text-base font-normal text-muted-foreground ml-2">({totalEntries})</span>
        </h1>
        <p className="text-sm text-muted-foreground mt-1">{t("decisions.ui.subtitle")}</p>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          placeholder="Search by document, agent, or action"
          className="pl-9"
        />
      </div>

      <div className="rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8"></TableHead>
              <TableHead>{t("decisions.ui.type")}</TableHead>
              <TableHead>{t("decisions.ui.action")}</TableHead>
              <TableHead>{t("decisions.ui.status")}</TableHead>
              <TableHead>{t("decisions.ui.by")}</TableHead>
              <TableHead>{t("decisions.ui.confidence")}</TableHead>
              <TableHead>{t("decisions.ui.time")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredGroups.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  {t("decisions.ui.noRunsRecorded")}
                </TableCell>
              </TableRow>
            ) : (
              filteredGroups.map((group) => {
                const isMRExpanded = expandedMRs.has(group.document_id);
                return (
                  <React.Fragment key={group.document_id}>
                    {/* MR Header Row */}
                    <TableRow
                      className="cursor-pointer bg-muted/30 hover:bg-muted/50"
                      onClick={() => toggleMR(group.document_id)}
                    >
                      <TableCell>
                        <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                          {isMRExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRightIcon className="h-4 w-4" />}
                        </Button>
                      </TableCell>
                      <TableCell colSpan={4}>
                        <span className="font-mono text-sm font-semibold text-primary">{group.document_id}</span>
                        <span className="text-xs text-muted-foreground ml-2">
                          ({group.entries.length} {group.entries.length === 1 ? "entry" : "entries"})
                        </span>
                      </TableCell>
                      <TableCell></TableCell>
                      <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                        {(group.latestTime || "").substring(0, 19).replace("T", " ")}
                      </TableCell>
                    </TableRow>

                    {/* Entries within MR */}
                    {isMRExpanded && group.entries.map((entry) => {
                      const isWorkflow = entry.type === "workflow";
                      const isWfExpanded = expandedWorkflows.has(entry.decision_id);
                      const isLoadingWf = loadingChildren.has(entry.decision_id);
                      const children = isWfExpanded ? getWorkflowChildren(entry) : [];

                      return (
                        <React.Fragment key={entry.decision_id}>
                          <TableRow
                            className="cursor-pointer"
                            onClick={() => { setSelectedItem(entry); setShowDetail(true); }}
                          >
                            <TableCell className="w-8">
                              {isWorkflow ? (
                                <Button
                                  variant="ghost" size="sm" className="h-6 w-6 p-0 ml-2"
                                  onClick={(ev) => { ev.stopPropagation(); toggleWorkflow(entry); }}
                                >
                                  {isLoadingWf ? <Spinner size="sm" /> : isWfExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRightIcon className="h-4 w-4" />}
                                </Button>
                              ) : (
                                <span className="inline-block w-4 ml-4" />
                              )}
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                {typeIcon(entry.type, entry.agent)}
                                <span className="text-xs font-medium">{typeLabel(entry)}</span>
                              </div>
                            </TableCell>
                            <TableCell>
                              {entry.action ? (
                                <StatusBadge
                                  status={
                                    (entry.action || "").includes("APPROVED") || (entry.action || "").includes("ACCEPTED")
                                      ? "approved"
                                      : (entry.action || "").includes("REJECTED")
                                        ? "rejected"
                                        : "warning"
                                  }
                                >
                                  {entry.action}
                                </StatusBadge>
                              ) : entry.recommendation ? (
                                <span className="text-xs text-muted-foreground">{entry.recommendation}</span>
                              ) : "--"}
                            </TableCell>
                            <TableCell>{statusBadge(entry.status, t)}</TableCell>
                            <TableCell className="text-sm">{decidedByLabel(entry)}</TableCell>
                            <TableCell className="text-sm">
                              {entry.confidence ? `${(Number(entry.confidence) * 100).toFixed(0)}%` : "--"}
                            </TableCell>
                            <TableCell className="text-xs whitespace-nowrap">
                              {(entry.decided_at || "").substring(0, 19).replace("T", " ")}
                            </TableCell>
                          </TableRow>

                          {/* Workflow children (collapsed by default) */}
                          {isWfExpanded && children.map((child) => (
                            <TableRow
                              key={child.id || child.decision_id || `${entry.decision_id}-${child.agent}`}
                              className="cursor-pointer bg-muted/10"
                              onClick={() => {
                                setSelectedItem({
                                  ...child,
                                  decision_id: child.id || child.decision_id || `${entry.decision_id}-${child.agent}`,
                                  document_id: entry.document_id,
                                  document_type: entry.document_type,
                                } as RunEntry);
                                setShowDetail(true);
                              }}
                            >
                              <TableCell>
                                <span className="inline-block w-4 ml-6 border-l border-b border-muted-foreground/30 h-3" />
                              </TableCell>
                              <TableCell>
                                <div className="flex items-center gap-2">
                                  {typeIcon(child.type, child.agent)}
                                  <span className="text-xs font-medium">{typeLabel({
                                    ...child,
                                    decision_id: "", document_type: "", document_id: "",
                                    action: "", status: "", decided_by: "", decided_at: "",
                                    recommendation: "", confidence: 0, summary: "", justification: "",
                                    parent_id: "", agent_recommendation: "", agent_confidence: "", agent_reasoning: "",
                                  } as RunEntry)}</span>
                                </div>
                              </TableCell>
                              <TableCell>
                                {child.action ? (
                                  <StatusBadge
                                    status={(child.action || "").includes("APPROVED") ? "approved" : (child.action || "").includes("REJECTED") ? "rejected" : "warning"}
                                  >
                                    {child.action}
                                  </StatusBadge>
                                ) : child.recommendation ? (
                                  <span className="text-xs text-muted-foreground">{child.recommendation}</span>
                                ) : "--"}
                              </TableCell>
                              <TableCell>{statusBadge(child.status, t)}</TableCell>
                              <TableCell className="text-sm">{child.decided_by || "AI Agent"}</TableCell>
                              <TableCell className="text-sm">
                                {child.confidence ? `${(Number(child.confidence) * 100).toFixed(0)}%` : "--"}
                              </TableCell>
                              <TableCell className="text-xs whitespace-nowrap">
                                {((child as any).completed_at || (child as any).started_at || "").substring(0, 19).replace("T", " ")}
                              </TableCell>
                            </TableRow>
                          ))}
                        </React.Fragment>
                      );
                    })}
                  </React.Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Detail Dialog */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent size="large">
          <DialogHeader>
            <DialogTitle>
              {selectedItem?.document_type} {selectedItem?.document_id} -- {selectedItem ? typeLabel(selectedItem) : ""}
            </DialogTitle>
          </DialogHeader>
          {selectedItem && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("decisions.ui.type")}</div>
                  <div className="flex items-center gap-2 mt-1">
                    {typeIcon(selectedItem.type, selectedItem.agent)}
                    <span className="text-sm">{typeLabel(selectedItem)}</span>
                  </div>
                </div>
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("decisions.ui.status")}</div>
                  <div className="mt-1">{statusBadge(selectedItem.status, t)}</div>
                </div>
              </div>

              {selectedItem.action && (
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("decisions.ui.action")}</div>
                  <div className="mt-1">
                    <StatusBadge
                      status={
                        (selectedItem.action || "").includes("APPROVE") || (selectedItem.action || "").includes("ACCEPTED")
                          ? "approved"
                          : (selectedItem.action || "").includes("REJECT")
                            ? "rejected"
                            : "warning"
                      }
                    >
                      {selectedItem.action}
                    </StatusBadge>
                  </div>
                </div>
              )}

              <div>
                <div className="text-xs font-medium text-muted-foreground">{t("decisions.ui.document")}</div>
                <div className="text-sm mt-1 font-mono">{selectedItem.document_type} {selectedItem.document_id}</div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("decisions.ui.by")}</div>
                  <div className="text-sm mt-1">{decidedByLabel(selectedItem)}</div>
                </div>
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("decisions.ui.time")}</div>
                  <div className="text-sm mt-1">{(selectedItem.decided_at || "").substring(0, 19).replace("T", " ")}</div>
                </div>
              </div>

              {selectedItem.recommendation && (
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("decisions.ui.recommendation")}</div>
                  <div className="mt-1 text-sm">
                    {selectedItem.recommendation}
                    {selectedItem.confidence ? ` (${(Number(selectedItem.confidence) * 100).toFixed(0)}% confidence)` : ""}
                  </div>
                </div>
              )}

              {selectedItem.justification && (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">{t("decisions.ui.justification")}</div>
                  <div className="rounded-lg border bg-muted/30 p-3 text-sm">{selectedItem.justification}</div>
                </div>
              )}

              {selectedItem.summary && (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">{t("decisions.ui.summary")}</div>
                  <AgentReasoning text={selectedItem.summary} />
                </div>
              )}

              {!selectedItem.justification && !selectedItem.summary && (
                <p className="text-sm text-muted-foreground">{t("decisions.ui.noAdditionalDetails")}</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
