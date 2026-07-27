// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState, useEffect, useCallback } from "react";
import { Bell } from "lucide-react";
import { api } from "../api";
import { resolveUserName } from "../lookups";
import { cn } from "@/lib/utils";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { useTranslation } from "react-i18next";

const POLL_INTERVAL = 30_000;
const STORAGE_KEY = "aria-notif-last-seen";
const MAX_ITEMS = 8;

function timeAgo(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function NotificationBell() {
  const { t } = useTranslation();
  const [decisions, setDecisions] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState(() => localStorage.getItem(STORAGE_KEY) || "");

  const fetchDecisions = useCallback(async () => {
    try {
      const items = await api.getDecisions();
      setDecisions((items || []).slice(0, MAX_ITEMS));
    } catch {
      // Silently fail — notifications are non-critical
    }
  }, []);

  useEffect(() => {
    fetchDecisions();
    const id = setInterval(fetchDecisions, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [fetchDecisions]);

  const unreadCount = lastSeen
    ? decisions.filter((d) => d.decided_at > lastSeen).length
    : decisions.length;

  const handleOpen = (isOpen: boolean) => {
    setOpen(isOpen);
    if (isOpen && decisions.length > 0) {
      const newest = decisions[0]?.decided_at || "";
      setLastSeen(newest);
      localStorage.setItem(STORAGE_KEY, newest);
    }
  };

  return (
    <Popover open={open} onOpenChange={handleOpen}>
      <PopoverTrigger asChild>
        <button className="relative flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
          <Bell className="h-4 w-4" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold text-destructive-foreground">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent>
        <div className="px-3 py-2 border-b">
          <p className="text-sm font-semibold">{t("notificationBell.ui.title")}</p>
        </div>
        <div className="max-h-80 overflow-y-auto">
          {decisions.length === 0 ? (
            <p className="px-3 py-6 text-sm text-center text-muted-foreground">{t("notificationBell.ui.noRecentActivity")}</p>
          ) : (
            decisions.map((d: any, i: number) => (
              <div
                key={d.decision_id || i}
                className={cn(
                  "flex items-start gap-2 px-3 py-2.5 border-b last:border-0",
                  d.decided_at > lastSeen && !open ? "bg-accent/50" : ""
                )}
              >
                <div className={cn(
                  "mt-0.5 h-2 w-2 rounded-full shrink-0",
                  d.action === "APPROVE" || d.action === "MATCHED" ? "bg-success" :
                  d.action === "REJECT" ? "bg-destructive" : "bg-warning"
                )} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs leading-snug">
                    <span className="font-medium">{d.document_type} {d.document_id}</span>
                    {" "}
                    <span className={cn(
                      d.action === "APPROVE" || d.action === "MATCHED" ? "text-success" :
                      d.action === "REJECT" ? "text-destructive" : "text-warning"
                    )}>
                      {d.action?.toLowerCase()}
                    </span>
                    {" by "}
                    <span className="font-medium">
                      {d.decided_by === "AI_AGENT" ? "AI Agent" :
                       d.decided_by === "AI_AGENT_PENDING" ? "AI (pending)" :
                       resolveUserName(d.decided_by)}
                    </span>
                  </p>
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    {d.decided_at ? timeAgo(d.decided_at) : ""}
                  </p>
                </div>
              </div>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
