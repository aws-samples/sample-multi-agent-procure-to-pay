// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function Spinner({ className, size = "default" }: { className?: string; size?: "sm" | "default" | "lg" }) {
  const sizeClass = size === "sm" ? "h-4 w-4" : size === "lg" ? "h-8 w-8" : "h-5 w-5";
  return <Loader2 className={cn("animate-spin text-muted-foreground", sizeClass, className)} />;
}
