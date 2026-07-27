// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(n: number | undefined | null, currency = "USD") {
  const num = typeof n === "number" ? n : parseFloat(String(n ?? 0));
  if (isNaN(num)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(num);
}

export function statusColor(status: string): string {
  const s = status?.toLowerCase();
  if (["approved", "ordered", "paid", "completed", "success"].some(v => s?.includes(v))) return "success";
  if (["pending", "draft"].some(v => s?.includes(v))) return "secondary";
  if (["overdue", "rejected", "cancelled", "error", "failed"].some(v => s?.includes(v))) return "destructive";
  if (["unpaid", "warning", "partially"].some(v => s?.includes(v))) return "warning";
  return "info";
}

export function statusLabel(status: string): string {
  return (status || "unknown").replace(/_/g, " ");
}
