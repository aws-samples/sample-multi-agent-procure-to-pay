// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Role-based access control for the P2P application.
 *
 * 6 roles matching the Entry Portal persona cards:
 *   - requester    → creates PRs via natural language, tracks own orders
 *   - approver     → reviews/approves PRs and POs, sees agent recommendations
 *   - ap_clerk     → handles invoices, 3-way match, payments, uploads invoices
 *   - executive    → read-only dashboards, KPIs, spend analytics, ROI
 *   - procurement  → full operational access: sourcing, POs, command center, config
 *   - admin        → everything (fallback for unknown roles)
 */

export type P2PRole = "requester" | "approver" | "ap_clerk" | "executive" | "procurement" | "admin";

export function resolveRole(roleAttr: string | undefined): P2PRole {
  const r = (roleAttr || "").toLowerCase().trim();
  if (r === "requester" || r === "requestor") return "requester";
  if (r === "approver" || r === "manager") return "approver";
  if (r === "ap_clerk" || r === "ap_analyst" || r === "ap") return "ap_clerk";
  if (r === "executive" || r === "exec" || r === "cfo") return "executive";
  if (r === "procurement" || r === "procurement_officer" || r === "proc") return "procurement";
  return "admin";
}

interface NavItem { label: string; href: string }
interface NavSep { type: "sep" }
type NavEntry = NavItem | NavSep;

const ALL_NAV: NavEntry[] = [
  { label: "Home", href: "/" },
  { label: "Dashboard", href: "/dashboard" },
  { type: "sep" },
  { label: "Requisitions", href: "/requisitions" },
  { label: "Sourcing", href: "/sourcing" },
  { label: "POs", href: "/purchase-orders" },
  { label: "Receipts", href: "/goods-receipts" },
  { label: "Invoices & Payments", href: "/invoices" },
  { type: "sep" },
  { label: "Chat", href: "/chat" },
  { label: "Command Center", href: "/command-center" },
  { label: "Decisions", href: "/decisions" },
  { label: "Config", href: "/configuration" },
  { label: "Architecture", href: "/architecture" },
];

const ROLE_ALLOWED: Record<P2PRole, Set<string> | "all"> = {
  requester: new Set([
    "/", "/chat", "/requisitions", "/dashboard",
  ]),
  approver: new Set([
    "/", "/dashboard", "/chat",
    "/requisitions", "/sourcing", "/purchase-orders", "/goods-receipts",
    "/command-center", "/decisions",
  ]),
  ap_clerk: new Set([
    "/", "/dashboard", "/chat",
    "/invoices", "/purchase-orders", "/goods-receipts",
    "/decisions",
  ]),
  executive: new Set([
    "/", "/dashboard", "/chat",
    "/command-center", "/decisions", "/architecture",
  ]),
  procurement: new Set([
    "/", "/dashboard", "/chat",
    "/requisitions", "/sourcing", "/purchase-orders", "/goods-receipts",
    "/invoices",
    "/command-center", "/decisions", "/configuration",
  ]),
  admin: "all",
};

export function getNavForRole(role: P2PRole): NavEntry[] {
  const allowed = ROLE_ALLOWED[role];
  if (allowed === "all") return ALL_NAV;

  const filtered: NavEntry[] = [];
  let lastWasSep = true;
  for (const item of ALL_NAV) {
    if ("type" in item && item.type === "sep") {
      if (!lastWasSep) filtered.push(item);
      lastWasSep = true;
    } else if ("href" in item && allowed.has(item.href)) {
      filtered.push(item);
      lastWasSep = false;
    }
  }
  if (filtered.length > 0 && "type" in filtered[filtered.length - 1]) filtered.pop();
  return filtered;
}

export function isRouteAllowed(role: P2PRole, path: string): boolean {
  const allowed = ROLE_ALLOWED[role];
  if (allowed === "all") return true;
  return allowed.has(path);
}

export function getChatSuggestions(role: P2PRole): string[] {
  switch (role) {
    case "requester":
      return [
        "I need 50 units of bearing assembly SKU MAT-003",
        "Order 100 stainless steel bolts from Acme Industrial",
        "What's the status of my recent requisitions?",
        "Reorder the same materials as my last PR",
        "I need safety gloves and goggles for the plant floor",
      ];
    case "approver":
      return [
        "Show me all pending requisitions needing approval",
        "Which PRs have HIGH risk scores?",
        "What's the total value of pending approvals?",
        "Compare this month's spend to last month",
        "Show me requisitions over $10,000",
      ];
    case "ap_clerk":
      return [
        "Which invoices have discrepancies?",
        "Show me unmatched invoices",
        "What's the total value of pending payments?",
        "Which vendors have outstanding invoices?",
        "Show me invoices with price variances over 3%",
      ];
    case "executive":
      return [
        "Give me a P2P pipeline summary",
        "What's our total spend this period?",
        "How many decisions were auto-approved vs human?",
        "Show me the agent ROI metrics",
        "Which vendors represent the highest spend?",
      ];
    case "procurement":
      return [
        "Show me all open purchase orders",
        "Which vendors have the best delivery scores?",
        "Are there consolidation opportunities?",
        "What's the status of the sourcing pipeline?",
        "Show me POs pending goods receipt",
      ];
    default:
      return [
        "Give me a summary of the P2P pipeline",
        "Which invoices have discrepancies?",
        "What's the total value of pending requisitions?",
        "Show me POs from Acme Industrial Supply",
        "Which vendors do we use most?",
      ];
  }
}

export function getChatSystemContext(role: P2PRole, username: string, sapUser: string): string {
  switch (role) {
    case "requester":
      return `The current user is "${username}" (SAP user: ${sapUser}) with role REQUESTER. They can CREATE purchase requisitions using natural language and track their own orders. They should ONLY see requisitions where ERNAM matches "${sapUser}". When they describe materials they need, use the create_requisition tool to submit a PR on their behalf. Always confirm what you're creating before submitting.`;
    case "approver":
      return `The current user is "${username}" with role APPROVER. They review and approve purchase requisitions and purchase orders. They can see all pipeline data and agent recommendations. They cannot create requisitions.`;
    case "ap_clerk":
      return `The current user is "${username}" with role AP_CLERK. They handle invoice processing, 3-way matching, and payment scheduling. They focus on invoices, payments, and vendor reconciliation. They cannot see or modify requisitions.`;
    case "executive":
      return `The current user is "${username}" with role EXECUTIVE. They have read-only access to dashboards, KPIs, and spend analytics. Provide high-level summaries and trends. They cannot approve, reject, or modify any documents.`;
    case "procurement":
      return `The current user is "${username}" with role PROCUREMENT OFFICER. They manage the full sourcing and purchasing pipeline — vendors, POs, sourcing decisions, and operational configuration. They can see everything except invoice processing.`;
    default:
      return `The current user is "${username}" with role ADMIN. They have full access to all procurement data.`;
  }
}
