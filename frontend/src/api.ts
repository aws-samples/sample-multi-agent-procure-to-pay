// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { getToken } from "./auth";
import type { Invoice } from "./types/p2p";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { headers, ...options });
  if (res.status === 401) { window.location.href = "/"; throw new Error("Session expired"); }
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

// ─── API response shapes ──────────────────────────────────────────────────

/** Dashboard metrics strip on the entry portal. */
export interface DashboardMetrics {
  decisions?: { today?: number };
  purchase_orders?: { open?: number };
  vendors?: number;
}

/** A single logged agent/system error. */
export interface ErrorRecord {
  timestamp?: string;
  agent_name?: string;
  category?: string;
  severity?: string;
  document_type?: string;
  document_id?: string;
  message?: string;
  retry_eligible?: boolean;
}

/** Aggregated error counts. */
export interface ErrorSummary {
  total_unresolved?: number;
  human_action_needed?: number;
  by_severity?: Record<string, number>;
}

/**
 * A decision / run-history entry from the audit trail. Covers both top-level
 * decisions and nested workflow/agent runs (linked via parent_id).
 */
export interface DecisionRun {
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
  timestamp?: string;
  result?: unknown;
  runs?: DecisionRun[] | string;
}

/** Response for the per-document run history endpoint. */
export interface DocumentRunsResponse {
  runs?: DecisionRun[];
}

/** Chat agent reply. */
export interface ChatResponse {
  response?: string;
  generated_title?: string;
  session_id?: string;
  tools_used?: string[];
}

/** Document lifecycle / state-tracking record. */
export interface LifecycleRecord {
  status?: string;
  current_step?: string;
  runs?: string | unknown[];
  rejected_by?: string;
  po_order_id?: string;
}

/** Async invoice extraction/creation job status. */
export interface InvoiceJobStatus {
  status?: string;
  step?: string;
  extraction?: unknown;
  invoice?: Invoice;
  error?: string;
}

/** Result of scheduling a payment. */
export interface SchedulePaymentResponse {
  payment_id?: string;
  amount?: number;
  mode_of_payment?: string;
  error?: string;
}

/** Persisted chat session summary. */
export interface ChatSessionRecord {
  id: string;
  title: string;
  last_message?: string;
  timestamp?: string;
}

/** Persisted chat message. */
export interface ChatMessageRecord {
  role: string;
  content: string;
  timestamp?: string;
  tools_used?: string[];
}

export const api = {
  // Admin
  getDataStatus: () => request<Record<string, unknown>>("/admin/status"),
  getDashboardMetrics: () => request<DashboardMetrics>("/dashboard/metrics"),
  resetData: () => request<Record<string, unknown>>("/admin/reset", { method: "POST" }),

  // Errors
  getErrors: () => request<ErrorRecord[]>("/errors/"),
  getErrorSummary: () => request<ErrorSummary>("/errors/summary/counts"),

  // Audit trail & run history
  getDecisions: () => request<DecisionRun[]>("/decisions/"),
  getDocumentRuns: (documentId: string) => request<DocumentRunsResponse>(`/decisions/${encodeURIComponent(documentId)}/runs`),
  recordDecision: (body: {
    document_type: string;
    document_id: string;
    action: string;
    justification?: string;
    agent_recommendation?: string;
    agent_confidence?: number;
    agent_reasoning?: string;
    match_result?: string;
  }) => request<Record<string, unknown>>("/decisions/", { method: "POST", body: JSON.stringify(body) }),

  // Chat agent
  chatWithAgent: (message: string, role?: string, roleContext?: string, conversationHistory?: { role: string; content: string }[], sessionId?: string) =>
    request<ChatResponse>(`/agents/chat`, {
      method: "POST",
      body: JSON.stringify({ message, role: role || "admin", role_context: roleContext || "", conversation_history: conversationHistory || [], session_id: sessionId || "" }),
    }),

  // Document lifecycle (state tracking)
  getLifecycle: (documentId: string) => request<LifecycleRecord>(`/lifecycle/${encodeURIComponent(documentId)}`),

  // Configuration
  getApprovalRules: () => request<Record<string, unknown>>("/config/rules"),
  getAgentConfigs: () => request<Record<string, unknown>[]>("/config/agents"),
  getContracts: () => request<Record<string, unknown>[]>("/config/contracts"),
  getDelegations: () => request<Record<string, unknown>[]>("/config/delegations"),
  createDelegation: (body: {
    delegate_to: string;
    start_date: string;
    end_date: string;
    spend_limit: number;
    notes?: string;
  }) => request<Record<string, unknown>>("/config/delegations", { method: "POST", body: JSON.stringify(body) }),

  // Invoice upload — extract only (preview, no ERP creation)
  uploadInvoice: async (file: File) => {
    const token = await getToken();
    const formData = new FormData();
    formData.append("file", file);
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}/invoices/upload`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json();
  },

  // Invoice upload — start async extraction + creation job
  analyzeAndCreateInvoice: async (file: File) => {
    const token = await getToken();
    const formData = new FormData();
    formData.append("file", file);
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}/invoices/analyzeAndCreateInvoice`, {
      method: "POST",
      headers,
      body: formData,
    });
    if (!res.ok) throw new Error(`Failed: ${res.status}`);
    return res.json();
  },

  // Poll job status
  getInvoiceJobStatus: async (jobId: string) => {
    return request<InvoiceJobStatus>(`/invoices/jobs/${encodeURIComponent(jobId)}`);
  },

  // Schedule payment for an approved invoice (records workflow in runs[])
  schedulePayment: (data: {
    invoice_id: string; supplier_id: string; amount: number;
    order_id?: string; mode_of_payment?: string;
    deductions?: { account: string; cost_center: string; amount: number }[];
    match_result?: unknown; payment_analysis?: unknown;
  }) => request<SchedulePaymentResponse>("/invoices/schedulePayment", { method: "POST", body: JSON.stringify(data) }),

  // Chat session persistence
  getChatSessions: () => request<{ sessions: ChatSessionRecord[]; user: string }>("/chat/sessions"),
  getChatMessages: (sessionId: string) =>
    request<{ session_id: string; messages: ChatMessageRecord[] }>(`/chat/sessions/${encodeURIComponent(sessionId)}`),
  saveChatMessage: (sessionId: string, role: string, content: string, toolsUsed: string[] = []) =>
    request<Record<string, unknown>>("/chat/message", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, role, content, tools_used: toolsUsed }),
    }),
  createChatSession: (sessionId: string, title: string) =>
    request<Record<string, unknown>>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, title }),
    }),
  deleteChatSession: (sessionId: string) =>
    request<Record<string, unknown>>(`/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
};
