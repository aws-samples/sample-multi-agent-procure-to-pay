// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/10 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-transparent bg-destructive/10 text-destructive",
        outline: "text-foreground",
        success: "border-transparent bg-success/10 text-success",
        warning: "border-transparent bg-warning/10 text-warning",
        info: "border-transparent bg-info/10 text-info",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  // nosemgrep -- react-props-spreading: shadcn/Radix primitive — prop forwarding is the intended contract
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export function StatusBadge({ status, children }: { status: string; children?: React.ReactNode }) {
  const s = status?.toLowerCase() || "";
  let variant: BadgeProps["variant"] = "secondary";
  if (["approved", "ordered", "paid", "completed", "success", "matched"].some(v => s.includes(v))) variant = "success";
  else if (["overdue", "rejected", "cancelled", "error", "failed", "destructive"].some(v => s.includes(v))) variant = "destructive";
  else if (["unpaid", "warning", "partially", "overdue"].some(v => s.includes(v))) variant = "warning";
  else if (["pending", "draft", "submitted"].some(v => s.includes(v))) variant = "info";
  return <Badge variant={variant}>{children || status?.replace(/_/g, " ") || "unknown"}</Badge>;
}
