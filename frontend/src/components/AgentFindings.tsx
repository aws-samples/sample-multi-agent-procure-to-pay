// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState } from "react";
import { CheckCircle2, AlertTriangle, XCircle, ChevronDown, ChevronRight } from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { useTranslation } from "react-i18next";

interface Finding {
  check: string;
  status: string;
  detail: string;
}

interface AgentFindingsProps {
  findings: Finding[];
}

function FindingIcon({ status }: { status: string }) {
  if (status === "FAIL") return <XCircle className="h-4 w-4 text-destructive shrink-0" />;
  if (status === "WARN") return <AlertTriangle className="h-4 w-4 text-warning shrink-0" />;
  return <CheckCircle2 className="h-4 w-4 text-success shrink-0" />;
}

export default function AgentFindings({ findings }: AgentFindingsProps) {
  const { t } = useTranslation();

  const warnings = (findings || []).filter((f) => f.status === "WARN");
  const failures = (findings || []).filter((f) => f.status === "FAIL");
  const passes = (findings || []).filter((f) => f.status === "PASS");
  const concerns = [...failures, ...warnings];
  const [passesOpen, setPassesOpen] = useState(concerns.length === 0);

  if (!findings || findings.length === 0) return null;

  return (
    <div className="space-y-4">
      {concerns.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide pb-1.5">
            {t("agentFindings.ui.areasOfConcern", { count: concerns.length })}
          </div>
          {concerns.map((f, i) => (
            <div key={i} className="pb-2">
              <div className="flex items-center gap-2">
                <FindingIcon status={f.status} />
                <span className="text-sm font-medium">{f.check}</span>
              </div>
              <p className="text-xs text-muted-foreground pl-6 pt-0.5">
                {f.detail}
              </p>
            </div>
          ))}
        </div>
      )}

      {passes.length > 0 && (
        <Collapsible open={passesOpen} onOpenChange={setPassesOpen}>
          <CollapsibleTrigger className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer bg-transparent border-none p-0">
            {passesOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            Passed Checks ({passes.length})
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            {passes.map((f, i) => (
              <div key={i} className="pb-2">
                <div className="flex items-center gap-2">
                  <FindingIcon status={f.status} />
                  <span className="text-sm font-medium">{f.check}</span>
                </div>
                <p className="text-xs text-muted-foreground pl-6 pt-0.5">
                  {f.detail}
                </p>
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}
