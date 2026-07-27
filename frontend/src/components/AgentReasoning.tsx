// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState } from "react";

interface AgentReasoningProps {
  text: string;
}

const TRUNCATE_LENGTH = 300;

/** Render a text segment with **bold** markdown support. */
function renderFormatted(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i}>{part.slice(2, -2)}</strong>;
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

export default function AgentReasoning({ text }: AgentReasoningProps) {
  const [expanded, setExpanded] = useState(false);

  if (!text) return null;

  const isLong = text.length > TRUNCATE_LENGTH;
  const displayText = isLong && !expanded
    ? text.slice(0, TRUNCATE_LENGTH).replace(/\s+\S*$/, "") + "..."
    : text;

  // Split on numbered sections (1-2 digit only to avoid SAP doc IDs)
  const sections = displayText.split(
    /(?=\(\d{1,2}\)\s|(?:^|\n)\d{1,2}\.\s(?=[A-Z]))/
  );

  return (
    <div>
      {sections.length <= 1 ? (
        <p className="text-sm text-foreground leading-relaxed">{renderFormatted(displayText)}</p>
      ) : (
        sections.map((section, i) => {
          const trimmed = section.trim();
          if (!trimmed) return null;
          const isNumbered = /^\(\d{1,2}\)|^\d{1,2}\./.test(trimmed);
          if (isNumbered && i > 0) {
            return (
              <div key={i} className="reasoning-section pl-3 border-l-2 border-border mb-2"
                style={{ animationDelay: `${i * 80}ms` }}>
                <p className="text-sm text-foreground leading-relaxed">{renderFormatted(trimmed)}</p>
              </div>
            );
          }
          return (
            <p key={i} className="text-sm text-foreground leading-relaxed pb-1">
              {renderFormatted(trimmed)}
            </p>
          );
        })
      )}
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="bg-transparent border-none cursor-pointer text-primary text-xs py-1 px-0 hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
