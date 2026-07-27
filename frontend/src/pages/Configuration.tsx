// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { api } from "../api";
import { formatCurrency } from "@/lib/utils";
import { useTranslation } from "react-i18next";

function RuleValue({ label, value, unit }: { label: string; value: any; unit?: string }) {
  const display = value === 0 ? "Never" : value === true ? "Yes" : value === false ? "No" : `${value}${unit || ""}`;
  return (
    <div className="pb-2">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="text-sm">{display}</div>
    </div>
  );
}

const DELEGATE_OPTIONS = [
  { value: "maria.chen", label: "Maria Chen (Requester)" },
  { value: "sarah.johnson", label: "Sarah Johnson (Approver)" },
  { value: "priya.patel", label: "Priya Patel (AP Clerk)" },
  { value: "gary.wilson", label: "Gary Wilson (Executive)" },
  { value: "jake.rodriguez", label: "Jake Rodriguez (Procurement)" },
];

export default function Configuration() {
  const { t } = useTranslation();
  const [rules, setRules] = useState<any>(null);
  const [agents, setAgents] = useState<any[]>([]);
  const [contracts, setContracts] = useState<any[]>([]);
  const [delegations, setDelegations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedPrompts, setExpandedPrompts] = useState<Record<string, boolean>>({});
  const [showDelegationForm, setShowDelegationForm] = useState(false);
  const [delegationForm, setDelegationForm] = useState({ delegate_to: "", start_date: "", end_date: "", spend_limit: 10000, notes: "" });
  const [creatingDelegation, setCreatingDelegation] = useState(false);

  const fetchAll = () => {
    setLoading(true);
    Promise.all([
      api.getApprovalRules(),
      api.getAgentConfigs(),
      api.getContracts().catch(() => []),
      api.getDelegations().catch(() => []),
    ]).then(([r, a, c, d]) => {
      setRules(r);
      setAgents(a);
      setContracts(c);
      setDelegations(d);
      setLoading(false);
    }).catch(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);

  if (loading) return <div className="flex items-center justify-center py-20"><Spinner size="lg" /></div>;
  if (!rules) return <div className="text-center text-muted-foreground py-8">{t("configuration.ui.couldNotLoad")}</div>;

  const agentRules = rules.agent_rules || {};
  const reqRules = agentRules.requisition || {};
  const invRules = agentRules.invoice_matching || {};
  const srcRules = agentRules.sourcing || {};

  return (
    <div className="animate-in space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("configuration.ui.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("configuration.ui.subtitle")}</p>
      </div>

      <Tabs defaultValue="rules">
        <TabsList>
          <TabsTrigger value="rules">{t("configuration.ui.tabRules")}</TabsTrigger>
          <TabsTrigger value="contracts">{t("configuration.ui.tabContracts")}</TabsTrigger>
          <TabsTrigger value="delegations">{t("configuration.ui.tabDelegations")}</TabsTrigger>
          <TabsTrigger value="agents">{t("configuration.ui.tabAgents")}</TabsTrigger>
        </TabsList>

        {/* ── Rules Tab ── */}
        <TabsContent value="rules" className="space-y-4 mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardHeader><CardTitle className="text-base">{t("configuration.ui.requisitionThresholds")}</CardTitle></CardHeader>
              <CardContent className="space-y-1">
                <RuleValue label="Auto-Approve" value={`$${(reqRules.auto_approve_threshold || 5000).toLocaleString()}`} />
                <RuleValue label="Escalation" value={`$${(reqRules.escalation_threshold || 50000).toLocaleString()}`} />
                <RuleValue label="Duplicate Window" value={reqRules.duplicate_window_days || 30} unit=" days" />
                <RuleValue label="Price Variance (LOW)" value={`<= ${reqRules.price_variance_low_pct || 10}%`} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">{t("configuration.ui.invoiceMatchingTolerances")}</CardTitle></CardHeader>
              <CardContent className="space-y-1">
                <RuleValue label="Price Tolerance" value={invRules.price_tolerance_pct || 3} unit="%" />
                <RuleValue label="Quantity Tolerance" value={invRules.quantity_tolerance_pct || 0} unit="% (exact)" />
                <RuleValue label="Auto-Approve Confidence" value={invRules.auto_approve_confidence || 0.9} />
                <RuleValue label="Partial Invoices" value={invRules.allow_partial_invoices} />
                <RuleValue label="Rounding Tolerance" value={`$${invRules.max_amount_tolerance || 50}`} />
              </CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader><CardTitle className="text-base">{t("configuration.ui.sourcingScoringWeights")}</CardTitle></CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(srcRules.weights || {}).map(([k, v]: [string, any]) => (
                  <div key={k} className="text-center">
                    <div className="text-2xl font-bold text-primary">{v}%</div>
                    <div className="text-xs text-muted-foreground capitalize">{k}</div>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-3 pt-2 border-t">
                {t("configuration.ui.minScoreTieBreak", { minScore: srcRules.min_score_for_recommendation || 50, tieBreak: srcRules.tie_break_preference || "delivery" })}
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Contracts Tab ── */}
        <TabsContent value="contracts" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("configuration.ui.frameworkAgreements")}</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("configuration.ui.agreement")}</TableHead>
                    <TableHead>{t("configuration.ui.vendor")}</TableHead>
                    <TableHead>{t("configuration.ui.materialGroup")}</TableHead>
                    <TableHead className="text-right">{t("configuration.ui.discount")}</TableHead>
                    <TableHead className="text-right">{t("configuration.ui.value")}</TableHead>
                    <TableHead>{t("configuration.ui.utilization")}</TableHead>
                    <TableHead>{t("configuration.ui.status")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {contracts.map((c: any) => {
                    const pct = Math.round((c.utilized_value / c.total_value) * 100);
                    const barColor = pct > 90 ? "bg-red-500" : pct > 70 ? "bg-amber-500" : "bg-green-500";
                    return (
                      <TableRow key={c.agreement_id}>
                        <TableCell className="font-mono text-xs">{c.agreement_id}</TableCell>
                        <TableCell className="font-medium">{c.vendor}</TableCell>
                        <TableCell>{c.material_group}</TableCell>
                        <TableCell className="text-right">{c.discount_pct}%</TableCell>
                        <TableCell className="text-right font-mono">{formatCurrency(c.total_value)}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2 min-w-32">
                            <div className="flex-1 h-2 rounded-full bg-muted">
                              <div className={`h-2 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
                            </div>
                            <span className={`text-xs font-bold ${pct > 90 ? "text-red-500" : pct > 70 ? "text-amber-500" : "text-green-500"}`}>{pct}%</span>
                          </div>
                        </TableCell>
                        <TableCell><StatusBadge status={c.status}>{c.status}</StatusBadge></TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Delegations Tab ── */}
        <TabsContent value="delegations" className="mt-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">{t("configuration.ui.approvalDelegations")}</CardTitle>
              <Button size="sm" onClick={() => setShowDelegationForm(true)}>
                <Plus className="h-4 w-4 mr-1" /> {t("configuration.ui.createDelegation")}
              </Button>
            </CardHeader>
            <CardContent>
              {delegations.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("configuration.ui.noDelegations")}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("configuration.ui.from")}</TableHead>
                      <TableHead>{t("configuration.ui.to")}</TableHead>
                      <TableHead>{t("configuration.ui.start")}</TableHead>
                      <TableHead>{t("configuration.ui.end")}</TableHead>
                      <TableHead className="text-right">{t("configuration.ui.spendLimit")}</TableHead>
                      <TableHead>{t("configuration.ui.status")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {delegations.map((d: any) => (
                      <TableRow key={d.decision_id}>
                        <TableCell>{d.delegate_from}</TableCell>
                        <TableCell className="font-medium">{d.delegate_to}</TableCell>
                        <TableCell>{d.start_date}</TableCell>
                        <TableCell>{d.end_date}</TableCell>
                        <TableCell className="text-right font-mono">{formatCurrency(parseFloat(d.spend_limit || "0"))}</TableCell>
                        <TableCell><StatusBadge status={d.status || "active"}>{d.status || "active"}</StatusBadge></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Agents Tab ── */}
        <TabsContent value="agents" className="space-y-4 mt-4">
          {agents.map((agent: any) => (
            <Card key={agent.id}>
              <CardHeader><CardTitle className="text-base">{agent.name}</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("configuration.ui.objective")}</div>
                  <div className="text-sm mt-1">{agent.objective}</div>
                </div>
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{t("configuration.ui.decisionOutcomes")}</div>
                  <div className="text-sm mt-1">{agent.decisions}</div>
                </div>
                <Collapsible
                  open={expandedPrompts[agent.id] || false}
                  onOpenChange={(open: boolean) => setExpandedPrompts((prev) => ({ ...prev, [agent.id]: open }))}
                >
                  <CollapsibleTrigger className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer bg-transparent border-none p-0 pt-2 border-t">
                    {expandedPrompts[agent.id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    {t("configuration.ui.viewSystemPrompt")}
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <pre className="mt-3 p-3 rounded-md bg-muted text-xs font-mono whitespace-pre-wrap max-h-72 overflow-auto">
                      {agent.system_prompt}
                    </pre>
                  </CollapsibleContent>
                </Collapsible>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>

      {/* Create Delegation Dialog */}
      <Dialog open={showDelegationForm} onOpenChange={setShowDelegationForm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("configuration.ui.createApprovalDelegation")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("configuration.ui.delegateTo")}</Label>
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={delegationForm.delegate_to}
                onChange={(e) => setDelegationForm({ ...delegationForm, delegate_to: e.target.value })}
              >
                <option value="">{t("configuration.ui.selectPerson")}</option>
                {DELEGATE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{t("configuration.ui.startDate")}</Label>
                <Input type="date" value={delegationForm.start_date} onChange={(e) => setDelegationForm({ ...delegationForm, start_date: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t("configuration.ui.endDate")}</Label>
                <Input type="date" value={delegationForm.end_date} onChange={(e) => setDelegationForm({ ...delegationForm, end_date: e.target.value })} />
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t("configuration.ui.spendLimitDollars")}</Label>
              <Input type="number" value={delegationForm.spend_limit} onChange={(e) => setDelegationForm({ ...delegationForm, spend_limit: parseFloat(e.target.value) || 0 })} />
            </div>
            <div className="space-y-2">
              <Label>{t("configuration.ui.notesOptional")}</Label>
              <Input value={delegationForm.notes} onChange={(e) => setDelegationForm({ ...delegationForm, notes: e.target.value })} placeholder={t("configuration.ui.notesPlaceholder")} />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setShowDelegationForm(false)}>{t("configuration.ui.cancel")}</Button>
              <Button
                loading={creatingDelegation}
                disabled={!delegationForm.delegate_to || !delegationForm.start_date || !delegationForm.end_date}
                onClick={async () => {
                  setCreatingDelegation(true);
                  try {
                    await api.createDelegation(delegationForm);
                    setShowDelegationForm(false);
                    setDelegationForm({ delegate_to: "", start_date: "", end_date: "", spend_limit: 10000, notes: "" });
                    const d = await api.getDelegations().catch(() => []);
                    setDelegations(d);
                  } catch (e) { console.error(e); }
                  setCreatingDelegation(false);
                }}
              >
                {t("configuration.ui.createDelegation")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
