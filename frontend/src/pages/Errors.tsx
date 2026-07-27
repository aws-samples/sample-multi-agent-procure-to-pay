// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/badge";
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table";
import { Spinner } from "@/components/ui/spinner";
import { api } from "../api";
import type { ErrorRecord, ErrorSummary } from "../api";
import { useTranslation } from "react-i18next";

export default function Errors() {
  const { t } = useTranslation();
  const [errors, setErrors] = useState<ErrorRecord[]>([]);
  const [summary, setSummary] = useState<ErrorSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.getErrors(), api.getErrorSummary()]).then(([errs, sum]) => {
      setErrors(errs);
      setSummary(sum);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

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
        <h1 className="text-2xl font-bold tracking-tight">{t("errors.ui.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("errors.ui.subtitle")}</p>
      </div>

      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("errors.ui.unresolvedErrors")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{summary.total_unresolved}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("errors.ui.humanActionNeeded")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{summary.human_action_needed}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("errors.ui.bySeverity")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {Object.entries(summary.by_severity || {}).map(([k, v]) => (
                  <div key={k}>
                    <StatusBadge status={k === "HIGH" || k === "CRITICAL" ? "error" : k === "MEDIUM" ? "warning" : "info"}>
                      {k}: {v as number}
                    </StatusBadge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("errors.ui.errorLog", { count: errors.length })}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("errors.ui.colTime")}</TableHead>
                <TableHead>{t("errors.ui.colAgent")}</TableHead>
                <TableHead>{t("errors.ui.colCategory")}</TableHead>
                <TableHead>{t("errors.ui.colSeverity")}</TableHead>
                <TableHead>{t("errors.ui.colDocument")}</TableHead>
                <TableHead>{t("errors.ui.colMessage")}</TableHead>
                <TableHead>{t("errors.ui.colRetryable")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {errors.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                    {t("errors.ui.noErrors")}
                  </TableCell>
                </TableRow>
              ) : (
                errors.map((e: ErrorRecord, i: number) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs whitespace-nowrap">{e.timestamp?.substring(0, 19)}</TableCell>
                    <TableCell>{e.agent_name}</TableCell>
                    <TableCell>{e.category}</TableCell>
                    <TableCell>
                      <StatusBadge status={e.severity === "HIGH" || e.severity === "CRITICAL" ? "error" : e.severity === "MEDIUM" ? "warning" : "info"}>
                        {e.severity}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className="text-xs">{`${e.document_type || ""} ${e.document_id || ""}`}</TableCell>
                    <TableCell className="max-w-xs truncate text-xs">{e.message?.substring(0, 60)}</TableCell>
                    <TableCell>{e.retry_eligible ? "Yes" : "No"}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
