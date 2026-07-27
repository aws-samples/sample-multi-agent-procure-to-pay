// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { erpApi } from "../erpApi";
import type { SpendSummary, SupplierPerformance, BudgetStatus } from "../types/p2p";
import { useAuth } from "../AuthContext";
import { resolveRole, isRouteAllowed } from "../roles";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { Button } from "@/components/ui/button";
import { formatCurrency } from "@/lib/utils";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from "recharts";
import {
  DollarSign,
  ShoppingCart,
  Receipt,
  AlertTriangle,
  Package,
  FileText,
  ArrowRight,
  RefreshCw,
  TrendingUp,
  Users,
  CheckCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";

const PIE_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444"];

const SUPPLIER_COLORS = ["#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#06b6d4", "#14b8a6", "#10b981", "#f59e0b"];

export default function Dashboard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const role = resolveRole(user?.role);

  const [summary, setSummary] = useState<SpendSummary | null>(null);
  const [suppliers, setSuppliers] = useState<SupplierPerformance[]>([]);
  const [budgets, setBudgets] = useState<BudgetStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, perfData, budgetData] = await Promise.all([
        erpApi.getSpendSummary(),
        erpApi.getSupplierPerformance().catch(() => ({ suppliers: [] })),
        erpApi.getBudgetStatus().catch(() => ({ budgets: [] as BudgetStatus[] })),
      ]);
      setSummary(data);
      setSuppliers(perfData.suppliers || []);
      setBudgets(budgetData.budgets || []);
    } catch (e: any) {
      setError(e.message || "Failed to load dashboard data");
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="animate-in space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("dashboard.ui.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("dashboard.ui.subtitle")}</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Error state */}
      {error && !summary && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-6 text-center text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && !summary && (
        <div className="flex items-center justify-center gap-2 py-12">
          <Spinner />
          <span className="text-sm text-muted-foreground">{t("dashboard.ui.loading")}</span>
        </div>
      )}

      {summary && (
        <div className="space-y-6">
          {/* Hero KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardContent className="p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
                    <DollarSign className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">{t("dashboard.ui.totalSpend")}</p>
                    <p className="text-2xl font-bold font-mono tracking-tight">
                      {formatCurrency(summary.total_spend)}
                    </p>
                    <p className="text-xs text-muted-foreground">{summary.total_suppliers} suppliers</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-500/10">
                    <ShoppingCart className="h-5 w-5 text-green-600 dark:text-green-400" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">{t("dashboard.ui.purchaseOrders")}</p>
                    <p className="text-2xl font-bold font-mono tracking-tight">
                      {summary.total_orders}
                    </p>
                    <p className="text-xs text-muted-foreground">{summary.open_orders} open</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/10">
                    <Receipt className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">{t("dashboard.ui.invoices")}</p>
                    <p className="text-2xl font-bold font-mono tracking-tight">
                      {summary.total_invoices}
                    </p>
                    <p className="text-xs text-muted-foreground">{summary.unpaid_invoices} unpaid</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Secondary KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardContent className="p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-500/10">
                    <Package className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">{t("dashboard.ui.openOrders")}</p>
                    <p className="text-2xl font-bold font-mono tracking-tight">
                      {summary.open_orders}
                    </p>
                    <p className="text-xs text-muted-foreground">{t("dashboard.ui.ofTotal", { count: summary.total_orders })}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
                    <FileText className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">{t("dashboard.ui.unpaidInvoices")}</p>
                    <p className="text-2xl font-bold font-mono tracking-tight">
                      {summary.unpaid_invoices}
                    </p>
                    <p className="text-xs text-muted-foreground">{t("dashboard.ui.ofTotal", { count: summary.total_invoices })}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-500/10">
                    <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">{t("dashboard.ui.overdueInvoices")}</p>
                    <p className="text-2xl font-bold font-mono tracking-tight">
                      {summary.overdue_invoices}
                    </p>
                    <div className="mt-0.5">
                      {summary.overdue_invoices > 0 ? (
                        <StatusBadge status="overdue">{t("dashboard.ui.actionNeeded")}</StatusBadge>
                      ) : (
                        <StatusBadge status="completed">{t("dashboard.ui.noneOverdue")}</StatusBadge>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Top Suppliers by Spend */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("dashboard.ui.topSuppliersBySpend")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {suppliers.length > 0 ? (
                  <ResponsiveContainer width="100%" height={Math.max(250, suppliers.slice(0, 8).length * 50)}>
                    <BarChart
                      data={suppliers.slice(0, 8).sort((a: SupplierPerformance, b: SupplierPerformance) => (b.total_spend || 0) - (a.total_spend || 0))}
                      layout="vertical"
                      margin={{ top: 0, right: 10, left: 0, bottom: 0 }}
                    >
                      <XAxis type="number" tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}K`} fontSize={11} />
                      <YAxis type="category" dataKey="supplier_name" width={130} fontSize={11} tickLine={false} />
                      <Tooltip formatter={(v: any) => formatCurrency(v as number)} />
                      <Bar dataKey="total_spend" radius={[0, 4, 4, 0]}>
                        {suppliers.slice(0, 8).sort((a, b) => (b.total_spend || 0) - (a.total_spend || 0)).map((_, i) => (
                          <Cell key={i} fill={SUPPLIER_COLORS[i % SUPPLIER_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="py-8 text-center text-sm text-muted-foreground">{t("dashboard.ui.noSupplierData")}</p>
                )}
              </CardContent>
            </Card>

            {/* Order Status */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("dashboard.ui.orderInvoiceStatus")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-center">
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie
                        data={[
                          { name: "Open Orders", value: summary.open_orders || 0 },
                          { name: "Completed", value: Math.max(0, (summary.total_orders || 0) - (summary.open_orders || 0)) },
                          { name: "Unpaid Invoices", value: summary.unpaid_invoices || 0 },
                          { name: "Overdue", value: summary.overdue_invoices || 0 },
                        ].filter((d) => d.value > 0)}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={90}
                        paddingAngle={3}
                        dataKey="value"
                        label={({ name, value }: any) => `${name}: ${value}`}
                        labelLine={false}
                      >
                        {[0, 1, 2, 3].map((i) => (
                          <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Budget Utilization */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                {t("dashboard.ui.budgetUtilizationByCostCenter")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {budgets.length > 0 ? budgets.map((b) => {
                const pct = Math.round(b.utilization_pct);
                const color = b.exceeded ? "bg-red-500" : pct > 90 ? "bg-red-500" : pct > 70 ? "bg-amber-500" : "bg-green-500";
                return (
                  <div key={b.cost_center} className="flex items-center gap-3">
                    <span className="text-sm w-28 shrink-0">{b.cost_center_name}</span>
                    <div className="flex-1 h-2.5 rounded-full bg-muted">
                      <div className={`h-2.5 rounded-full ${color} transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
                    </div>
                    <span className="text-xs font-mono w-20 text-right text-muted-foreground">
                      {formatCurrency(b.actual_spend)} / {formatCurrency(b.budget_amount)}
                    </span>
                    <span className={`text-xs font-bold w-10 text-right ${b.exceeded ? "text-red-500" : pct > 90 ? "text-red-500" : pct > 70 ? "text-amber-500" : "text-green-500"}`}>
                      {pct}%
                    </span>
                  </div>
                );
              }) : (
                <p className="py-4 text-center text-sm text-muted-foreground">{t("dashboard.ui.noBudgetData")}</p>
              )}
            </CardContent>
          </Card>

          {/* Pipeline Flow */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                {t("dashboard.ui.pipelineFlow")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap items-center justify-center gap-3">
                {[
                  { label: "Requisitions", href: "/requisitions", color: "green" },
                  { label: "Purchase Orders", count: summary.total_orders, action: summary.open_orders, href: "/purchase-orders", color: "blue" },
                  { label: "Goods Receipts", href: "/goods-receipts", color: "purple" },
                  { label: "Invoices", count: summary.total_invoices, action: summary.unpaid_invoices, href: "/invoices", color: "cyan" },
                ]
                  .filter((step) => isRouteAllowed(role, step.href))
                  .map((step, i, arr) => (
                    <div key={step.label} className="flex items-center gap-3">
                      <Card
                        className="min-w-[140px] cursor-pointer p-4 text-center transition-all hover:shadow-md"
                        onClick={() => navigate(step.href)}
                      >
                        {step.count !== undefined && (
                          <div className={`text-2xl font-bold font-mono ${
                            step.color === "blue" ? "text-blue-600 dark:text-blue-400" :
                            step.color === "green" ? "text-green-600 dark:text-green-400" :
                            step.color === "purple" ? "text-purple-600 dark:text-purple-400" :
                            "text-cyan-600 dark:text-cyan-400"
                          }`}>
                            {step.count}
                          </div>
                        )}
                        <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          {step.label}
                        </div>
                        {step.action !== undefined && step.action > 0 && (
                          <div className="mt-2">
                            <StatusBadge status="unpaid">{step.action} need action</StatusBadge>
                          </div>
                        )}
                        {step.action !== undefined && step.action === 0 && (
                          <div className="mt-2">
                            <StatusBadge status="completed">{t("dashboard.ui.allClear")}</StatusBadge>
                          </div>
                        )}
                        <button
                          className="mt-2 text-xs text-blue-600 hover:underline dark:text-blue-400"
                          onClick={(e) => { e.stopPropagation(); navigate(step.href); }}
                        >
                          {t("dashboard.ui.view")}
                        </button>
                      </Card>
                      {i < arr.length - 1 && (
                        <ArrowRight className="h-5 w-5 text-border shrink-0" />
                      )}
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>

          {/* Detail cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("dashboard.ui.ordersSummary")}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-blue-500" />
                  <span className="text-sm">{summary.total_orders} Total Orders</span>
                </div>
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                  <span className="text-sm">{summary.open_orders} Open</span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-green-500" />
                  <span className="text-sm">{summary.total_orders - summary.open_orders} Completed</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("dashboard.ui.invoicesSummary")}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-blue-500" />
                  <span className="text-sm">{summary.total_invoices} Total Invoices</span>
                </div>
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                  <span className="text-sm">{summary.unpaid_invoices} Unpaid</span>
                </div>
                <div className="flex items-center gap-2">
                  {summary.overdue_invoices > 0 ? (
                    <AlertTriangle className="h-4 w-4 text-red-500" />
                  ) : (
                    <CheckCircle className="h-4 w-4 text-green-500" />
                  )}
                  <span className="text-sm">{summary.overdue_invoices} Overdue</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("dashboard.ui.spendOverview")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex justify-around pt-1">
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1.5 mb-1">
                      <DollarSign className="h-4 w-4 text-blue-500" />
                    </div>
                    <div className="text-xl font-bold font-mono text-blue-600 dark:text-blue-400">
                      {formatCurrency(summary.total_spend)}
                    </div>
                    <div className="mt-0.5 text-xs uppercase text-muted-foreground">{t("dashboard.ui.totalSpend")}</div>
                  </div>
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1.5 mb-1">
                      <Users className="h-4 w-4 text-purple-500" />
                    </div>
                    <div className="text-xl font-bold font-mono text-purple-600 dark:text-purple-400">
                      {summary.total_suppliers}
                    </div>
                    <div className="mt-0.5 text-xs uppercase text-muted-foreground">{t("dashboard.ui.suppliers")}</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
