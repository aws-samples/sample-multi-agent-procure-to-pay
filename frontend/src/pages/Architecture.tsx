// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useTranslation } from "react-i18next";

export default function Architecture() {
  const { t } = useTranslation();
  return (
    <div className="space-y-6 animate-fade-up">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("architecture.ui.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t("architecture.ui.subtitle")}
        </p>
      </div>
      <div className="rounded-lg border bg-card p-4 flex justify-center">
        <img
          src="/arch-diagram.svg"
          alt="ARIA P2P Architecture Diagram"
          className="max-w-full rounded-lg"
        />
      </div>
    </div>
  );
}
