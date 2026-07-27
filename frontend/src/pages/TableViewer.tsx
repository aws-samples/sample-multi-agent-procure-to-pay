// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Table Viewer page -- placeholder.
 *
 * The raw table debug endpoint has been removed. ERP data is now accessed
 * via the canonical adapter API at /api/erp/*.
 */

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useTranslation } from "react-i18next";

export default function TableViewer() {
  const { t } = useTranslation();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tableViewer.ui.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          {t("tableViewer.ui.adapterInfoPrefix")}{" "}
          <code className="text-xs bg-muted px-1 py-0.5 rounded">/api/erp/*</code>. {t("tableViewer.ui.adapterInfoSuffix")}
        </p>
      </CardContent>
    </Card>
  );
}
