// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentStepList — Unified agent progress display.
 *
 * Two modes:
 *   Flat mode:  Renders progress[] strings as a vertical step list (standalone agents).
 *   Macro mode: Renders pre-computed StepItem[] (workflows, multi-phase operations).
 *
 * Also exports derivation helpers for workflow and rejection step states.
 */

import { CheckCircle2, Loader2, Circle, XCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";

// ─── Types ───────────────────────────────────────────────────────────────────

export type StepStatus = "pending" | "running" | "done" | "failed" | "rejected";

export interface StepItem {
  label: string;
  detail?: string;
  status: StepStatus;
}

export interface AgentStepListProps {
  /** Pre-defined steps (macro mode for workflows). If omitted, flat mode from progress[]. */
  steps?: StepItem[];
  /** Raw progress strings from useAgentStream (flat mode). */
  progress?: string[];
  /** Whether the agent is currently running. */
  isRunning: boolean;
  /** Header text shown above steps, e.g. "Requisition Agent". */
  title?: string;
  /** Duration in seconds (shown when complete). */
  durationSeconds?: number;
}

// ─── Icon for a step status ──────────────────────────────────────────────────

function StepIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="h-5 w-5 text-success shrink-0" />;
    case "running":
      return <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />;
    case "failed":
    case "rejected":
      return <XCircle className="h-5 w-5 text-destructive shrink-0" />;
    case "pending":
    default:
      return <Circle className="h-5 w-5 text-muted-foreground/30 shrink-0" />;
  }
}

function stepTextClass(status: StepStatus): string {
  switch (status) {
    case "done":
      return "text-foreground";
    case "running":
      return "text-primary";
    case "failed":
    case "rejected":
      return "text-destructive";
    default:
      return "text-muted-foreground";
  }
}

// ─── Main component ──────────────────────────────────────────────────────────

// Patterns that are macro-level workflow events (not tool-call sub-steps)
const MACRO_PATTERNS = [
  "Starting P2P", "Step 1", "Step 2", "Step 3",
  "Evaluating suppliers", "Analyzing requisition",
  "Auto-approved", "Human-Approved", "awaiting",
  "Purchase Order", "PO generation",
  "complete:", "complete —",
];

function isToolCallEvent(step: string): boolean {
  return !MACRO_PATTERNS.some((p) => step.includes(p));
}

export default function AgentStepList({
  steps: macroSteps,
  progress,
  isRunning,
  title,
  durationSeconds,
}: AgentStepListProps) {
  const { t } = useTranslation();
  // Derive steps based on mode
  const steps: StepItem[] = macroSteps
    ? macroSteps
    : (progress || []).map((step, i, arr) => ({
        label: step,
        status: isRunning && i === arr.length - 1 ? "running" as const : "done" as const,
      }));

  // In macro mode, extract tool-call sub-steps to show under the running step (deduped)
  const toolSubSteps = macroSteps && progress
    ? progress.filter(isToolCallEvent).filter((s, i, arr) => arr.indexOf(s) === i)
    : [];

  // In flat mode, dedupe consecutive identical steps
  if (!macroSteps) {
    const seen = new Set<string>();
    const deduped: StepItem[] = [];
    for (const s of steps) {
      if (!seen.has(s.label)) {
        seen.add(s.label);
        deduped.push(s);
      }
    }
    // Reassign status: last one running if isRunning, rest done
    deduped.forEach((s, i) => {
      s.status = isRunning && i === deduped.length - 1 ? "running" : "done";
    });
    steps.length = 0;
    steps.push(...deduped);
  }

  if (steps.length === 0 && isRunning) {
    return (
      <div className="flex items-center gap-3">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span className="text-sm font-medium">{title ? `${title} is working...` : "Processing..."}</span>
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {title && steps.length > 0 && (
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">{title}</p>
      )}
      {steps.map((step, i) => (
        <div key={i} className="flex gap-3">
          <div className="flex flex-col items-center">
            <StepIcon status={step.status} />
            {i < steps.length - 1 && <div className="w-px flex-1 bg-border mt-1" />}
          </div>
          <div className="flex-1 pb-3">
            <p className={cn("text-sm font-medium", stepTextClass(step.status))}>
              {step.label}
            </p>
            {step.detail && (
              <p className="text-xs text-muted-foreground mt-0.5">{step.detail}</p>
            )}
            {step.status === "running" && !step.detail && !macroSteps && (
              <p className="text-xs text-muted-foreground mt-0.5">{t("agentProgress.ui.processing")}</p>
            )}
            {/* Show tool-call sub-steps under the currently running macro step */}
            {step.status === "running" && macroSteps && toolSubSteps.length > 0 && (
              <div className="mt-1.5 space-y-1 pl-1">
                {toolSubSteps.map((sub, j) => (
                  <div key={j} className="flex items-center gap-2 text-xs text-muted-foreground">
                    {isRunning && j === toolSubSteps.length - 1 ? (
                      <Loader2 className="h-3 w-3 animate-spin text-primary shrink-0" />
                    ) : (
                      <CheckCircle2 className="h-3 w-3 text-success shrink-0" />
                    )}
                    <span>{sub}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
      {!isRunning && durationSeconds != null && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground pt-1">
          <Clock className="h-3.5 w-3.5" />
          Completed in {durationSeconds.toFixed(1)}s
        </div>
      )}
    </div>
  );
}

// ─── Derivation helpers for workflows ────────────────────────────────────────

/** Derive 4-step workflow status from progress event strings.
 *
 * Workflow order: Step 1 = Sourcing → Step 2 = Requisition Analysis → Gate → PO
 */
export function deriveWorkflowSteps(progress: string[]): StepItem[] {
  const joined = progress.join(" ");

  // Step 1: Sourcing Evaluation
  const step1Done = joined.includes("Step 1 complete");
  const step1Running = !step1Done && (joined.includes("Step 1:") || joined.includes("Evaluating suppliers") || joined.includes("Starting P2P"));
  const step1Detail = progress.find((p) => p.includes("Step 1 complete"))?.replace("Step 1 complete: ", "") || "";

  // Step 2: Requisition Analysis
  const step2Done = joined.includes("Step 2 complete");
  const step2Running = !step2Done && (joined.includes("Step 2:") || joined.includes("Analyzing requisition"));
  const step2Detail = progress.find((p) => p.includes("Step 2 complete"))?.replace("Step 2 complete: ", "") || "";

  // Approval Gate
  const gateDetail = progress.find((p) =>
    p.includes("Auto-approved") || p.includes("Human-Approved") || p.includes("awaiting")
  ) || "";
  const gateLabel = gateDetail.includes("Auto-approved")
    ? "Auto-Approved"
    : gateDetail.includes("Human-Approved")
      ? "Human-Approved"
      : "Approval Gate";

  // Step 3: PO Generation
  const step3Done = joined.includes("Purchase Order") && joined.includes("created");
  const step3Running = !step3Done && joined.includes("Step 3:");
  const step3Detail = progress.find((p) => p.includes("Purchase Order") && p.includes("created")) || "";

  const poFailed = joined.includes("PO generation failed");
  const poFailDetail = poFailed ? (progress.find((p) => p.includes("PO generation failed")) || "") : "";

  return [
    { label: "Sourcing Evaluation", status: step1Done ? "done" : step1Running ? "running" : "pending", detail: step1Detail },
    { label: "Requisition Analysis", status: step2Done ? "done" : step2Running ? "running" : "pending", detail: step2Detail },
    { label: gateLabel, status: gateDetail ? "done" : "pending", detail: gateDetail },
    {
      label: "PO Generation",
      status: poFailed ? "failed" : step3Done ? "done" : step3Running ? "running" : "pending",
      detail: poFailed ? poFailDetail : step3Detail,
    },
  ];
}

/** Static rejection stepper: steps 1+2 done, gate rejected, PO skipped. */
export function deriveRejectionSteps(): StepItem[] {
  return [
    { label: "Sourcing Evaluation", status: "done", detail: "Complete" },
    { label: "Requisition Analysis", status: "done", detail: "Complete" },
    { label: "Approval Gate", status: "rejected", detail: "Rejected by reviewer" },
    { label: "PO Generation", status: "pending", detail: "Skipped" },
  ];
}
