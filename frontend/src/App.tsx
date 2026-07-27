// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from "react";
import { Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AuthProvider, useAuth } from "./AuthContext";
import { useTheme } from "./ThemeContext";
import { resolveRole, getNavForRole, isRouteAllowed } from "./roles";
import { cn } from "./lib/utils";
import { Sun, Moon, Menu, ChevronDown, LogOut } from "lucide-react";
import Dashboard from "./pages/Dashboard";
import Requisitions from "./pages/Requisitions";
import Invoices from "./pages/Invoices";
import Decisions from "./pages/Decisions";
import Sourcing from "./pages/Sourcing";
import PurchaseOrders from "./pages/PurchaseOrders";
import GoodsReceipts from "./pages/GoodsReceipts";
import Errors from "./pages/Errors";
import Configuration from "./pages/Configuration";
import EntryPortal from "./pages/EntryPortal";
import CommandCenter from "./pages/CommandCenter";
import AgentChat from "./pages/AgentChat";
import Architecture from "./pages/Architecture";
import Login from "./pages/Login";
import NotificationBell from "./components/NotificationBell";

// Local dev fallback — only used when Cognito is not configured (VITE_COGNITO_POOL_ID unset)
const LOCAL_DEV_USER = {
  username: "local.dev",
  email: "dev@localhost",
  role: "admin",
  sapUser: "DEVUSER",
  department: "Development",
};

function NavDropdown({
  label,
  items,
  navigate,
  location,
}: {
  label: string;
  items: { label: string; href: string }[];
  navigate: (path: string) => void;
  location: { pathname: string };
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const hasActive = items.some((i) => location.pathname === i.href);

  React.useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        className={cn(
          "flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
          "hover:bg-accent hover:text-accent-foreground",
          hasActive ? "text-primary bg-accent" : "text-muted-foreground"
        )}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="true"
      >
        {label}
        <ChevronDown
          className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 min-w-[180px] rounded-md border bg-popover text-popover-foreground shadow-lg z-50 py-1 animate-fade-in">
          {items.map((item) => (
            <button
              key={item.href}
              className={cn(
                "w-full text-left px-3 py-2 text-sm transition-colors",
                "hover:bg-accent hover:text-accent-foreground",
                location.pathname === item.href
                  ? "text-primary font-medium bg-accent/50"
                  : "text-popover-foreground"
              )}
              onClick={() => {
                navigate(item.href);
                setOpen(false);
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function TopNav({ user, onLogout }: { user: any; onLogout: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const role = resolveRole(user?.role);
  const navItems = getNavForRole(role);

  // Split nav items into top-level and grouped
  const topLevel: { label: string; href: string }[] = [];
  const pipelineItems: { label: string; href: string }[] = [];
  const opsItems: { label: string; href: string }[] = [];

  const pipelinePaths = new Set([
    "/requisitions",
    "/sourcing",
    "/purchase-orders",
    "/goods-receipts",
    "/invoices",
  ]);
  const opsPaths = new Set([
    "/command-center",
    "/decisions",
    "/configuration",
    "/architecture",
  ]);

  for (const item of navItems) {
    if ("type" in item && item.type === "sep") continue;
    if (!("href" in item)) continue;
    if (pipelinePaths.has(item.href)) pipelineItems.push(item);
    else if (opsPaths.has(item.href)) opsItems.push(item);
    else topLevel.push(item);
  }

  return (
    <nav
      aria-label="Main navigation"
      className="sticky top-0 z-40 w-full border-b bg-background/80 backdrop-blur-lg"
    >
      <div className="flex h-14 items-center justify-between px-4 lg:px-6">
        {/* Left: brand + nav links */}
        <div className="flex items-center gap-6 min-w-0 flex-1">
          {/* Brand */}
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 shrink-0 group"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 text-white font-bold text-sm">
              {/* nosemgrep: jsx-not-internationalized -- brand logo glyph, not translatable copy */}
              A
            </div>
            <span className="text-base font-bold tracking-tight text-foreground">
              {/* nosemgrep: jsx-not-internationalized -- product brand name, not translatable */}
              ARIA
            </span>
          </button>

          {/* Desktop nav links */}
          <div className="hidden md:flex items-center gap-1">
            {topLevel.map((item) => {
              const active = location.pathname === item.href;
              return (
                <button
                  key={item.href}
                  className={cn(
                    "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                    "hover:bg-accent hover:text-accent-foreground",
                    active
                      ? "text-primary bg-accent"
                      : "text-muted-foreground"
                  )}
                  onClick={() => navigate(item.href)}
                >
                  {item.label}
                </button>
              );
            })}
            {pipelineItems.length > 0 && (
              <NavDropdown
                label={t("app.ui.pipeline")}
                items={pipelineItems}
                navigate={navigate}
                location={location}
              />
            )}
            {opsItems.length > 0 && (
              <NavDropdown
                label={t("app.ui.operations")}
                items={opsItems}
                navigate={navigate}
                location={location}
              />
            )}
          </div>
        </div>

        {/* Right: notifications, status, user, theme, sign out */}
        <div className="flex items-center gap-3">
          <NotificationBell />

          {/* Agent status */}
          <div className="hidden sm:flex items-center gap-2 text-xs text-muted-foreground">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-success" />
            </span>
            <span className="hidden lg:inline">{t("app.ui.allAgentsOnline")}</span>
          </div>

          {/* User */}
          <div className="hidden sm:flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15 text-primary text-xs font-semibold">
              {user.displayName?.split(" ").map((n: string) => n[0]).join("").substring(0, 2).toUpperCase() || "U"}
            </div>
            <div className="hidden lg:flex flex-col leading-tight">
              <span className="text-sm font-medium text-foreground">
                {user.displayName}
              </span>
              <span className="text-[11px] text-muted-foreground uppercase tracking-wider">
                {role}
              </span>
            </div>
          </div>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </button>

          {/* Sign out */}
          <button
            onClick={onLogout}
            className="hidden sm:inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("app.ui.signOut")}
          </button>

          {/* Mobile hamburger */}
          <button
            className="inline-flex md:hidden h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            onClick={() => setMobileOpen((o) => !o)}
            aria-label="Toggle navigation menu"
            aria-expanded={mobileOpen}
          >
            <Menu className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Mobile nav panel */}
      {mobileOpen && (
        <div className="md:hidden border-t bg-background/95 backdrop-blur-lg animate-fade-in">
          <div className="flex flex-col px-4 py-3 gap-1">
            {/* User info on mobile */}
            <div className="flex items-center gap-2 pb-3 mb-2 border-b sm:hidden">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15 text-primary text-xs font-semibold">
                {user.displayName?.split(" ").map((n: string) => n[0]).join("").substring(0, 2).toUpperCase() || "U"}
              </div>
              <div className="flex flex-col leading-tight">
                <span className="text-sm font-medium text-foreground">
                  {user.displayName}
                </span>
                <span className="text-[11px] text-muted-foreground uppercase tracking-wider">
                  {role}
                </span>
              </div>
            </div>

            {topLevel.map((item) => (
              <button
                key={item.href}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-md text-sm font-medium transition-colors",
                  "hover:bg-accent hover:text-accent-foreground",
                  location.pathname === item.href
                    ? "text-primary bg-accent"
                    : "text-muted-foreground"
                )}
                onClick={() => {
                  navigate(item.href);
                  setMobileOpen(false);
                }}
              >
                {item.label}
              </button>
            ))}

            {pipelineItems.length > 0 && (
              <>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mt-3 mb-1 px-3">
                  {t("app.ui.pipeline")}
                </div>
                {pipelineItems.map((item) => (
                  <button
                    key={item.href}
                    className={cn(
                      "w-full text-left px-3 py-2 rounded-md text-sm font-medium transition-colors",
                      "hover:bg-accent hover:text-accent-foreground",
                      location.pathname === item.href
                        ? "text-primary bg-accent"
                        : "text-muted-foreground"
                    )}
                    onClick={() => {
                      navigate(item.href);
                      setMobileOpen(false);
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </>
            )}

            {opsItems.length > 0 && (
              <>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mt-3 mb-1 px-3">
                  {t("app.ui.operations")}
                </div>
                {opsItems.map((item) => (
                  <button
                    key={item.href}
                    className={cn(
                      "w-full text-left px-3 py-2 rounded-md text-sm font-medium transition-colors",
                      "hover:bg-accent hover:text-accent-foreground",
                      location.pathname === item.href
                        ? "text-primary bg-accent"
                        : "text-muted-foreground"
                    )}
                    onClick={() => {
                      navigate(item.href);
                      setMobileOpen(false);
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </>
            )}

            {/* Mobile sign out */}
            <button
              onClick={onLogout}
              className="sm:hidden w-full text-left flex items-center gap-2 px-3 py-2 mt-2 rounded-md text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors border-t pt-3"
            >
              <LogOut className="h-3.5 w-3.5" />
              {t("app.ui.signOut")}
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}

function ProtectedRoute({
  path,
  role,
  children,
}: {
  path: string;
  role: string;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  if (!isRouteAllowed(resolveRole(role), path)) {
    React.useEffect(() => {
      navigate("/");
    }, [navigate]);
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        {t("app.ui.noAccess")}
      </div>
    );
  }
  return <>{children}</>;
}

function AppContent() {
  const { t } = useTranslation();
  const { user: realUser, loading, logout } = useAuth();
  const navigate = useNavigate();
  // Track whether this is a fresh login vs page refresh.
  // "unset" = initial load (don't redirect), null = was logged out, user = was logged in
  const prevUserRef = React.useRef<any>("unset");

  // In production (Cognito configured), require login. In local dev, use mock user.
  const hasCognito = !!import.meta.env.VITE_COGNITO_POOL_ID;
  const user = realUser || (hasCognito ? null : LOCAL_DEV_USER);

  // After fresh login (user transitions from null/logged-out to logged-in), redirect to home.
  // On page refresh, prevUserRef starts as "unset" so we skip the redirect.
  React.useEffect(() => {
    if (user && prevUserRef.current === null) {
      // Actual login: was null (logged out), now has user
      navigate("/", { replace: true });
    }
    if (prevUserRef.current === "unset" && user) {
      // Page refresh: skip redirect, just record the user
    }
    prevUserRef.current = user || null;
  }, [user]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen text-muted-foreground">
        {t("app.ui.loading")}
      </div>
    );
  }

  if (!user && hasCognito) {
    return <Login />;
  }

  if (!user) {
    return <Login />;
  }

  const role = user.role || "";

  return (
    <div className="min-h-screen bg-background text-foreground">
      <a href="#main-content" className="skip-to-content">
        {t("app.ui.skipToContent")}
      </a>
      <TopNav user={user} onLogout={logout} />
      <main id="main-content" className="mx-auto max-w-[1400px] px-4 py-6 lg:px-6">
        <Routes>
          <Route path="/" element={<EntryPortal />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute path="/dashboard" role={role}>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/command-center"
            element={
              <ProtectedRoute path="/command-center" role={role}>
                <CommandCenter />
              </ProtectedRoute>
            }
          />
          <Route
            path="/requisitions"
            element={
              <ProtectedRoute path="/requisitions" role={role}>
                <Requisitions />
              </ProtectedRoute>
            }
          />
          <Route
            path="/sourcing"
            element={
              <ProtectedRoute path="/sourcing" role={role}>
                <Sourcing />
              </ProtectedRoute>
            }
          />
          <Route
            path="/purchase-orders"
            element={
              <ProtectedRoute path="/purchase-orders" role={role}>
                <PurchaseOrders />
              </ProtectedRoute>
            }
          />
          <Route
            path="/goods-receipts"
            element={
              <ProtectedRoute path="/goods-receipts" role={role}>
                <GoodsReceipts />
              </ProtectedRoute>
            }
          />
          <Route
            path="/invoices"
            element={
              <ProtectedRoute path="/invoices" role={role}>
                <Invoices />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat"
            element={
              <ProtectedRoute path="/chat" role={role}>
                <AgentChat />
              </ProtectedRoute>
            }
          />
          <Route
            path="/decisions"
            element={
              <ProtectedRoute path="/decisions" role={role}>
                <Decisions />
              </ProtectedRoute>
            }
          />
          <Route
            path="/configuration"
            element={
              <ProtectedRoute path="/configuration" role={role}>
                <Configuration />
              </ProtectedRoute>
            }
          />
          <Route
            path="/architecture"
            element={
              <ProtectedRoute path="/architecture" role={role}>
                <Architecture />
              </ProtectedRoute>
            }
          />
          <Route
            path="/errors"
            element={
              <ProtectedRoute path="/errors" role={role}>
                <Errors />
              </ProtectedRoute>
            }
          />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
