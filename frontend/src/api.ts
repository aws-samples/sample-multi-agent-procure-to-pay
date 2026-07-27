// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { getToken } from "./auth";

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

export const api = {
  // Admin
  getDataStatus: () => request<any>("/admin/status"),
  getDashboardMetrics: () => request<any>("/dashboard/metrics"),
  resetData: () => request<any>("/admin/reset", { method: "POST" }),

  // Errors
  getErrors: () => request<any[]>("/errors/"),
  getErrorSummary: () => request<any>("/errors/summary/counts"),

  // Audit trail & run history
  getDecisions: () => request<any[]>("/decisions/"),
  getDocumentRuns: (documentId: string) => request<any>(`/decisions/${encodeURIComponent(documentId)}/runs`),
  recordDecision: (body: {
    document_type: string;
    document_id: string;
    action: string;
    justification?: string;
    agent_recommendation?: string;
    agent_confidence?: number;
    agent_reasoning?: string;
    match_result?: string;
  }) => request<any>("/decisions/", { method: "POST", body: JSON.stringify(body) }),

  // Chat agent
  chatWithAgent: (message: string, role?: string, roleContext?: string, conversationHistory?: { role: string; content: string }[], sessionId?: string) =>
    request<any>(`/agents/chat`, {
      method: "POST",
      body: JSON.stringify({ message, role: role || "admin", role_context: roleContext || "", conversation_history: conversationHistory || [], session_id: sessionId || "" }),
    }),

  // Document lifecycle (state tracking)
  getLifecycle: (documentId: string) => request<any>(`/lifecycle/${encodeURIComponent(documentId)}`),

  // Configuration
  getApprovalRules: () => request<any>("/config/rules"),
  getAgentConfigs: () => request<any[]>("/config/agents"),
  getContracts: () => request<any[]>("/config/contracts"),
  getDelegations: () => request<any[]>("/config/delegations"),
  createDelegation: (body: {
    delegate_to: string;
    start_date: string;
    end_date: string;
    spend_limit: number;
    notes?: string;
  }) => request<any>("/config/delegations", { method: "POST", body: JSON.stringify(body) }),

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
    return request<any>(`/invoices/jobs/${encodeURIComponent(jobId)}`);
  },

  // Schedule payment for an approved invoice (records workflow in runs[])
  schedulePayment: (data: {
    invoice_id: string; supplier_id: string; amount: number;
    order_id?: string; mode_of_payment?: string;
    deductions?: { account: string; cost_center: string; amount: number }[];
    match_result?: any; payment_analysis?: any;
  }) => request<any>("/invoices/schedulePayment", { method: "POST", body: JSON.stringify(data) }),

  // Chat session persistence
  getChatSessions: () => request<{ sessions: any[]; user: string }>("/chat/sessions"),
  getChatMessages: (sessionId: string) =>
    request<{ session_id: string; messages: any[] }>(`/chat/sessions/${encodeURIComponent(sessionId)}`),
  saveChatMessage: (sessionId: string, role: string, content: string, toolsUsed: string[] = []) =>
    request<any>("/chat/message", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, role, content, tools_used: toolsUsed }),
    }),
  createChatSession: (sessionId: string, title: string) =>
    request<any>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, title }),
    }),
  deleteChatSession: (sessionId: string) =>
    request<any>(`/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
};
