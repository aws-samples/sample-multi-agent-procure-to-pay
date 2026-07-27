// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState } from "react";
import { useAuth } from "../AuthContext";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle, Shield, ChevronDown, User } from "lucide-react";
import { useTranslation } from "react-i18next";

const DEMO_PASSWORD: string = import.meta.env.VITE_DEMO_PASSWORD || "";

const DEMO_USERS = [
  { email: "demo+maria@example.com", name: "Maria Chen", initials: "MC", role: "Requester", desc: "Natural language ordering", color: "from-blue-500 to-cyan-500" },
  { email: "demo+sarah@example.com", name: "Sarah Johnson", initials: "SJ", role: "Approver", desc: "AI-assisted review", color: "from-violet-500 to-purple-500" },
  { email: "demo+priya@example.com", name: "Priya Patel", initials: "PP", role: "AP Clerk", desc: "Invoice matching", color: "from-emerald-500 to-teal-500" },
  { email: "demo+gary@example.com", name: "Gary Wilson", initials: "GW", role: "Executive", desc: "Spend analytics", color: "from-amber-500 to-orange-500" },
  { email: "demo+jake@example.com", name: "Jake Rodriguez", initials: "JR", role: "Procurement", desc: "Full operations", color: "from-rose-500 to-pink-500" },
];

export default function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const quickLogin = async (email: string) => {
    if (!DEMO_PASSWORD) {
      setError("Quick-login disabled: VITE_DEMO_PASSWORD is not configured. Use the manual login form below.");
      setShowManual(true);
      return;
    }
    setLoading(email);
    setError("");
    try {
      await login(email, DEMO_PASSWORD);
    } catch (e: any) {
      setError(e.message || "Login failed");
    }
    setLoading("");
  };

  const handleManualLogin = async () => {
    setError("");
    if (!username || !password) { setError("Email and password required"); return; }
    setLoading("manual");
    try {
      await login(username, password);
    } catch (e: any) {
      setError(e.message || "Login failed");
    }
    setLoading("");
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center px-4 py-8 overflow-hidden">
      {/* Background video */}
      <video
        autoPlay
        loop
        muted
        playsInline
        className="absolute inset-0 w-full h-full object-cover"
      >
        <source src="/login-bg.mp4" type="video/mp4" />
      </video>

      {/* Blur + dark overlay */}
      <div className="absolute inset-0 backdrop-blur-sm bg-black/60" />

      {/* Login card — glass morphism */}
      <Card className="relative z-10 w-full max-w-md bg-card/70 backdrop-blur-xl border-white/10 shadow-2xl">
        <CardHeader className="text-center space-y-3 pb-4">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-500 to-orange-600 text-white font-bold text-2xl shadow-lg">
            {/* nosemgrep: jsx-not-internationalized -- brand logo glyph, not translatable copy */}
            A
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-card-foreground">
              {/* nosemgrep: jsx-not-internationalized -- product brand name, not translatable */}
              ARIA
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {t("login.ui.subtitle")}
            </p>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <p className="text-xs text-muted-foreground text-center">
            {t("login.ui.demoPrompt")}
          </p>

          <div className="flex flex-col gap-2">
            {DEMO_USERS.map((u) => (
              <button
                key={u.email}
                onClick={() => quickLogin(u.email)}
                disabled={!!loading}
                className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm border border-white/10 bg-white/5 transition-all hover:bg-white/10 hover:border-white/20 hover:shadow-sm disabled:opacity-50 disabled:cursor-not-allowed group"
              >
                <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${u.color} text-white text-xs font-semibold shadow-md`}>
                  {loading === u.email ? (
                    <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    u.initials
                  )}
                </div>
                <div className="flex-1 text-left">
                  <div className="font-medium text-card-foreground group-hover:text-white leading-tight">
                    {u.name}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {u.role} &middot; {u.desc}
                  </div>
                </div>
              </button>
            ))}
          </div>

          {/* Collapsible manual login */}
          <div className="border-t border-white/10 pt-3">
            <button
              onClick={() => setShowManual(!showManual)}
              className="flex items-center justify-center gap-1 w-full text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <User className="h-3 w-3" />
              {t("login.ui.signInWithCredentials")}
              <ChevronDown className={`h-3 w-3 transition-transform ${showManual ? "rotate-180" : ""}`} />
            </button>

            {showManual && (
              <div className="mt-3 space-y-3">
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Email"
                  autoComplete="username"
                  className="bg-white/5 border-white/10"
                />
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  autoComplete="current-password"
                  onKeyDown={(e) => { if (e.key === "Enter") handleManualLogin(); }}
                  className="bg-white/5 border-white/10"
                />
                <Button className="w-full" loading={loading === "manual"} onClick={handleManualLogin}>
                  {t("login.ui.signIn")}
                </Button>
              </div>
            )}
          </div>

          <div className="flex items-center justify-center gap-1.5 pt-1 text-[11px] text-muted-foreground">
            <Shield className="h-3 w-3" />
            {t("login.ui.securedByCognito")}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
