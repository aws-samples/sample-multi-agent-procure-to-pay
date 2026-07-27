// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { resolveRole } from "../roles";
import { api } from "../api";
import { erpApi } from "../erpApi";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { formatCurrency } from "@/lib/utils";
import {
  MessageSquare,
  ClipboardList,
  BarChart3,
  CheckCircle,
  Receipt,
  DollarSign,
  Package,
  Search,
  Settings,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

/* ── Icon resolver ── */
const ICON_MAP: Record<string, LucideIcon> = {
  chat: MessageSquare,
  requisitions: ClipboardList,
  dashboard: BarChart3,
  approval: CheckCircle,
  invoices: Receipt,
  payments: DollarSign,
  receipts: Package,
  sourcing: Search,
  config: Settings,
  admin: Zap,
};

function resolveIcon(route: string): LucideIcon {
  if (route.includes("chat")) return ICON_MAP.chat;
  if (route.includes("requisition")) return ICON_MAP.requisitions;
  if (route.includes("dashboard")) return ICON_MAP.dashboard;
  if (route.includes("command")) return ICON_MAP.admin;
  if (route.includes("invoice")) return ICON_MAP.invoices;
  if (route.includes("payment")) return ICON_MAP.payments;
  if (route.includes("goods") || route.includes("receipt")) return ICON_MAP.receipts;
  if (route.includes("sourcing")) return ICON_MAP.sourcing;
  if (route.includes("config")) return ICON_MAP.config;
  return ICON_MAP.dashboard;
}

/* ── Color classes for accent borders and icon backgrounds ── */
const COLOR_CLASSES: Record<string, { border: string; bg: string; text: string }> = {
  blue:   { border: "border-t-blue-500",   bg: "bg-blue-500/10",   text: "text-blue-600 dark:text-blue-400" },
  green:  { border: "border-t-green-500",  bg: "bg-green-500/10",  text: "text-green-600 dark:text-green-400" },
  purple: { border: "border-t-purple-500", bg: "bg-purple-500/10", text: "text-purple-600 dark:text-purple-400" },
  amber:  { border: "border-t-amber-500",  bg: "bg-amber-500/10",  text: "text-amber-600 dark:text-amber-400" },
  cyan:   { border: "border-t-cyan-500",   bg: "bg-cyan-500/10",   text: "text-cyan-600 dark:text-cyan-400" },
  red:    { border: "border-t-red-500",    bg: "bg-red-500/10",    text: "text-red-600 dark:text-red-400" },
};

/* ── Quick action card ── */
function ActionCard({
  title,
  subtitle,
  color,
  route,
  onClick,
}: {
  title: string;
  subtitle: string;
  color: string;
  route: string;
  onClick: () => void;
}) {
  const Icon = resolveIcon(route);
  const c = COLOR_CLASSES[color] || COLOR_CLASSES.blue;

  return (
    <Card
      className={`cursor-pointer border-t-3 ${c.border} transition-all hover:-translate-y-0.5 hover:shadow-md`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter") onClick(); }}
    >
      <CardContent className="p-5">
        <div className={`mb-3 inline-flex h-10 w-10 items-center justify-center rounded-lg ${c.bg}`}>
          <Icon className={`h-5 w-5 ${c.text}`} />
        </div>
        <div className="text-sm font-bold">{title}</div>
        <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{subtitle}</div>
      </CardContent>
    </Card>
  );
}

/* ── Stat pill ── */
const STAT_COLORS: Record<string, string> = {
  blue:   "text-blue-600 dark:text-blue-400",
  green:  "text-green-600 dark:text-green-400",
  purple: "text-purple-600 dark:text-purple-400",
  amber:  "text-amber-600 dark:text-amber-400",
  red:    "text-red-600 dark:text-red-400",
  cyan:   "text-cyan-600 dark:text-cyan-400",
};

function StatPill({ value, label, color }: { value: string | number; label: string; color: string }) {
  return (
    <div className="min-w-[80px] text-center">
      <div className={`text-2xl font-bold font-mono ${STAT_COLORS[color] || STAT_COLORS.blue}`}>
        {value}
      </div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
    </div>
  );
}

/* ── Status display map ──
 * Values are the canonical lowercase statuses returned by the adapter
 * (see backend/adapters/erpnext/field_maps.py map_status_to_canonical).
 */
const STATUS_MAP: Record<string, { label: string }> = {
  // Requisition statuses (Material Request)
  draft: { label: "Draft" },
  pending_approval: { label: "Pending Approval" },
  approved: { label: "Approved" },
  rejected: { label: "Rejected" },
  ordered: { label: "Ordered" },
  cancelled: { label: "Cancelled" },
  // Invoice statuses (Purchase Invoice)
  submitted: { label: "Submitted" },
  unpaid: { label: "Unpaid" },
  partially_paid: { label: "Partially Paid" },
  paid: { label: "Paid" },
  overdue: { label: "Overdue" },
  return: { label: "Return" },
  // PO / Receipt statuses
  partially_received: { label: "Partially Received" },
  completed: { label: "Completed" },
  closed: { label: "Closed" },
};

/* ── Recent items list ── */
function RecentItems({
  items,
  type,
  navigate,
}: {
  items: any[];
  type: "pr" | "invoice";
  navigate: (p: string) => void;
}) {
  const { t } = useTranslation();
  if (!items || items.length === 0) {
    return <p className="py-2 text-sm text-muted-foreground">{t("entryPortal.ui.noRecentItems")}</p>;
  }

  const display = items.slice(0, 5);

  return (
    <div className="flex flex-col">
      {display.map((item, i) => {
        const id = type === "pr" ? item.requisition_id : item.invoice_id;
        const status = item.status || "";
        const total = item.total_amount;
        const mapped = STATUS_MAP[status] || { label: status };

        return (
          <div
            key={i}
            className="flex items-center justify-between border-b border-border py-2 last:border-b-0"
          >
            <div className="flex items-center gap-3">
              <span className="font-mono text-xs text-blue-600 dark:text-blue-400">{id}</span>
              <span className="text-xs text-muted-foreground">
                {formatCurrency(parseFloat(total || 0))}
              </span>
            </div>
            <StatusBadge status={status}>{mapped.label}</StatusBadge>
          </div>
        );
      })}
      <button
        onClick={() => navigate(type === "pr" ? "/requisitions" : "/invoices")}
        className="mt-1 self-start text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
      >
        {t("entryPortal.ui.viewAll")} &rarr;
      </button>
    </div>
  );
}

/* ── Role-specific greeting and context ── */
const ROLE_CONFIG: Record<
  string,
  {
    greeting: string;
    description: string;
    actions: { title: string; subtitle: string; color: string; route: string }[];
  }
> = {
  requester: {
    greeting: "What do you need to order?",
    description: "Use the chat to describe what you need in plain English. The AI will handle the rest.",
    actions: [
      { title: "New Request via Chat", subtitle: "Describe what you need and the AI creates the requisition", color: "blue", route: "/chat" },
      { title: "My Requisitions", subtitle: "Track status of your purchase requests", color: "green", route: "/requisitions" },
      { title: "Dashboard", subtitle: "Overview of your procurement activity", color: "purple", route: "/dashboard" },
    ],
  },
  approver: {
    greeting: "Items awaiting your review",
    description: "Review AI-analyzed requisitions and make approval decisions.",
    actions: [
      { title: "Approval Queue", subtitle: "Requisitions with agent recommendations ready for review", color: "amber", route: "/requisitions" },
      { title: "Dashboard", subtitle: "Pipeline metrics and decision history", color: "blue", route: "/dashboard" },
      { title: "Command Center", subtitle: "Monitor agent fleet and workflow status", color: "cyan", route: "/command-center" },
      { title: "Ask the AI", subtitle: "Query procurement data in natural language", color: "green", route: "/chat" },
    ],
  },
  ap_clerk: {
    greeting: "Invoice matching queue",
    description: "Run 3-way matches and process payments with AI assistance.",
    actions: [
      { title: "Invoice Matching", subtitle: "3-way match invoices against POs and goods receipts", color: "blue", route: "/invoices" },
      { title: "Payments", subtitle: "Schedule payments and capture early discounts", color: "green", route: "/payments" },
      { title: "Goods Receipts", subtitle: "Verify deliveries against purchase orders", color: "amber", route: "/goods-receipts" },
      { title: "Ask the AI", subtitle: "Query invoice and payment data", color: "purple", route: "/chat" },
    ],
  },
  executive: {
    greeting: "Procurement intelligence",
    description: "Real-time spend analytics and pipeline visibility.",
    actions: [
      { title: "Spend Dashboard", subtitle: "Vendor spend, budget utilization, and trends", color: "blue", route: "/dashboard" },
      { title: "Command Center", subtitle: "Agent fleet status and workflow monitoring", color: "cyan", route: "/command-center" },
      { title: "Ask the AI", subtitle: "Natural language queries on procurement data", color: "green", route: "/chat" },
    ],
  },
  procurement: {
    greeting: "Procurement operations",
    description: "Full pipeline visibility from requisition to payment.",
    actions: [
      { title: "Command Center", subtitle: "Agent fleet, workflows, and pipeline monitoring", color: "cyan", route: "/command-center" },
      { title: "Requisitions", subtitle: "Review and analyze purchase requests", color: "green", route: "/requisitions" },
      { title: "Sourcing", subtitle: "Evaluate vendors with AI scoring", color: "amber", route: "/sourcing" },
      { title: "Invoices", subtitle: "3-way match and exception handling", color: "blue", route: "/invoices" },
      { title: "Ask the AI", subtitle: "Query any procurement data", color: "purple", route: "/chat" },
    ],
  },
  admin: {
    greeting: "System overview",
    description: "Full access to all procurement operations and configuration.",
    actions: [
      { title: "Command Center", subtitle: "Agent fleet and workflow monitoring", color: "cyan", route: "/command-center" },
      { title: "Dashboard", subtitle: "Pipeline metrics and spend analytics", color: "blue", route: "/dashboard" },
      { title: "Requisitions", subtitle: "Full requisition management", color: "green", route: "/requisitions" },
      { title: "Invoices", subtitle: "Invoice matching and processing", color: "amber", route: "/invoices" },
      { title: "Chat", subtitle: "Natural language procurement assistant", color: "purple", route: "/chat" },
      { title: "Configuration", subtitle: "Approval rules, delegations, contracts", color: "red", route: "/configuration" },
    ],
  },
};

export default function EntryPortal() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState<any>(null);
  const [recentPRs, setRecentPRs] = useState<any[]>([]);
  const [recentInvoices, setRecentInvoices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const role = resolveRole(user?.role);
  const config = ROLE_CONFIG[role] || ROLE_CONFIG.admin;
  const firstName = user?.displayName?.split(" ")[0] || "there";
  const capitalFirst = firstName.charAt(0).toUpperCase() + firstName.slice(1);

  useEffect(() => {
    const loadMetrics = api.getDashboardMetrics().catch(() => null);
    const loadPRs = ["requester", "approver", "procurement", "admin"].includes(role)
      ? erpApi.listRequisitions().then((r) => r.requisitions || []).catch(() => [])
      : Promise.resolve([]);
    const loadInvoices = ["ap_clerk", "procurement", "admin"].includes(role)
      ? erpApi.listInvoices().then((r) => r.invoices || []).catch(() => [])
      : Promise.resolve([]);

    Promise.all([loadMetrics, loadPRs, loadInvoices]).then(([m, prs, invs]) => {
      setMetrics(m);
      // Requesters only see their own PRs
      let filteredPRs = prs || [];
      if (role === "requester" && user?.email) {
        filteredPRs = filteredPRs.filter((p: any) => p.requester === user.email);
      }
      setRecentPRs(filteredPRs);
      setRecentInvoices(invs || []);
      setLoading(false);
    });
  }, [role, user?.email]);

  const pendingPRs = recentPRs.filter((p) => ["draft", "pending_approval"].includes(p.status)).length;
  const pendingInvoices = recentInvoices.filter((i) => ["submitted", "unpaid"].includes(i.status)).length;

  return (
    <div className="animate-in mx-auto max-w-4xl space-y-8">
      {/* Greeting */}
      <div className="pt-2">
        <p className="text-sm text-muted-foreground">{t("entryPortal.ui.welcomeBack", { name: capitalFirst })}</p>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">{config.greeting}</h1>
        <p className="mt-1.5 max-w-xl text-sm leading-relaxed text-muted-foreground">
          {config.description}
        </p>
      </div>

      {/* Key metrics strip */}
      {loading && (
        <div className="flex items-center gap-2 py-4">
          <Spinner size="sm" />
          <span className="text-sm text-muted-foreground">{t("entryPortal.ui.loadingWorkspace")}</span>
        </div>
      )}

      {!loading && metrics && (
        <div className="flex flex-wrap gap-8 py-2">
          {role === "requester" && (
            <>
              <StatPill value={pendingPRs} label="Your Pending PRs" color="amber" />
              <StatPill value={recentPRs.filter((p) => ["approved", "ordered"].includes(p.status)).length} label="Approved" color="green" />
              <StatPill value={recentPRs.length} label="Total Requests" color="blue" />
            </>
          )}
          {role === "approver" && (
            <>
              <StatPill value={pendingPRs} label="Awaiting Review" color="amber" />
              <StatPill value={metrics?.decisions?.today || 0} label="Decisions Today" color="green" />
              <StatPill value={metrics?.purchase_orders?.open || 0} label="Open POs" color="blue" />
            </>
          )}
          {role === "ap_clerk" && (
            <>
              <StatPill value={pendingInvoices} label="Unmatched Invoices" color="amber" />
              <StatPill value={recentInvoices.filter((i) => i.status === "paid").length} label="Paid" color="green" />
              <StatPill value={recentInvoices.length} label="Total Invoices" color="blue" />
            </>
          )}
          {role === "executive" && (
            <>
              <StatPill value={metrics?.purchase_orders?.open || 0} label="Open POs" color="blue" />
              <StatPill value={metrics?.decisions?.today || 0} label="Decisions Today" color="green" />
              <StatPill value={metrics?.vendors || 0} label="Active Vendors" color="purple" />
            </>
          )}
          {(role === "procurement" || role === "admin") && (
            <>
              <StatPill value={pendingPRs} label="Pending PRs" color="amber" />
              <StatPill value={pendingInvoices} label="Unmatched Invoices" color="red" />
              <StatPill value={metrics?.purchase_orders?.open || 0} label="Open POs" color="blue" />
              <StatPill value={metrics?.vendors || 0} label="Vendors" color="purple" />
            </>
          )}
        </div>
      )}

      {/* Quick actions grid */}
      <div>
        <div className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          {t("entryPortal.ui.quickActions")}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {config.actions.map((a, i) => (
            <ActionCard
              key={i}
              title={a.title}
              subtitle={a.subtitle}
              color={a.color}
              route={a.route}
              onClick={() => navigate(a.route)}
            />
          ))}
        </div>
      </div>

      {/* Recent activity -- role-specific */}
      {!loading && (
        <div
          className={`grid gap-5 ${
            (role === "ap_clerk" || role === "procurement" || role === "admin") && recentInvoices.length > 0
              ? "grid-cols-1 md:grid-cols-2"
              : "grid-cols-1"
          }`}
        >
          {["requester", "approver", "procurement", "admin"].includes(role) && recentPRs.length > 0 && (
            <Card>
              <CardContent className="p-5">
                <div className="mb-3 text-sm font-bold">
                  {role === "requester" ? t("entryPortal.ui.yourRecentRequests") : t("entryPortal.ui.recentRequisitions")}
                </div>
                <RecentItems items={recentPRs} type="pr" navigate={navigate} />
              </CardContent>
            </Card>
          )}
          {["ap_clerk", "procurement", "admin"].includes(role) && recentInvoices.length > 0 && (
            <Card>
              <CardContent className="p-5">
                <div className="mb-3 text-sm font-bold">{t("entryPortal.ui.recentInvoices")}</div>
                <RecentItems items={recentInvoices} type="invoice" navigate={navigate} />
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Footer strip */}
      <div className="flex items-center justify-between border-t border-border pt-3 mt-2">
        <span className="text-xs text-muted-foreground">
          {t("entryPortal.ui.footerTagline")}
        </span>
        <span className="text-xs text-muted-foreground">{t("entryPortal.ui.role", { role: role.toUpperCase() })}</span>
      </div>
    </div>
  );
}
