// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState } from "react";
import { Copy, Check } from "lucide-react";

interface SapIdCellProps {
  displayName: string;
  sapId: string;
  label?: string;
}

/**
 * Displays a human-readable name with a copy-to-clipboard button for the
 * underlying ID. Click the copy icon to copy the ID.
 */
export default function SapIdCell({ displayName, sapId, label = "SAP ID" }: SapIdCellProps) {
  const [copied, setCopied] = useState(false);

  if (!sapId || sapId === displayName) {
    return <span>{displayName}</span>;
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sapId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback ignored
    }
  };

  return (
    <span className="inline-flex items-center gap-1.5 group">
      <span>{displayName}</span>
      <button
        onClick={handleCopy}
        title={`Copy ${label}: ${sapId}`}
        className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </span>
  );
}
