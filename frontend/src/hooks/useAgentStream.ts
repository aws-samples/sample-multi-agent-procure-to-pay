// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * React hook for AgentCore streaming invocation.
 *
 * Calls AgentCore Runtime directly from the browser using SigV4-signed
 * requests via Cognito Identity Pool credentials. No Lambda proxy needed.
 */

import { useState, useCallback, useRef } from "react";
import { invokeAgentCore, isAgentCoreAvailable } from "../agentcore";

export interface ProgressStep {
  step: string;
  tool?: string;
  agent?: string;
  timestamp: number;
}

interface AgentStreamState {
  isRunning: boolean;
  progress: string[];
  progressSteps: ProgressStep[];
  result: any | null;
  meta: { tools_used?: any[]; metrics?: Record<string, number> } | null;
  error: string | null;
  source: "agentcore";
}

const INITIAL_STATE: AgentStreamState = {
  isRunning: false,
  progress: [],
  progressSteps: [],
  result: null,
  meta: null,
  error: null,
  source: "agentcore",
};

export function useAgentStream() {
  const [state, setState] = useState<AgentStreamState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL_STATE);
  }, []);

  const invoke = useCallback(async (agentName: string, documentId: string, extraPayload?: Record<string, string>) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    setState({ ...INITIAL_STATE, isRunning: true });

    if (!isAgentCoreAvailable(agentName)) {
      setState((s) => ({ ...s, isRunning: false, error: `AgentCore not configured for: ${agentName}` }));
      return;
    }

    try {
      for await (const event of invokeAgentCore(agentName, documentId, extraPayload)) {
        if (abortRef.current?.signal.aborted) return;

        if (event.type === "progress" && event.step) {
          setState((s) => ({
            ...s,
            progress: [...s.progress, event.step!],
            progressSteps: [...s.progressSteps, {
              step: event.step!,
              tool: event.tool,
              agent: event.agent,
              timestamp: Date.now(),
            }],
          }));
        } else if (event.type === "result") {
          setState((s) => ({
            ...s,
            isRunning: false,
            result: event.result || event,
            meta: { tools_used: event.tools_used, metrics: event.metrics },
          }));
          return;
        } else if (event.type === "error") {
          setState((s) => ({ ...s, isRunning: false, error: event.message || event.error || "Agent error" }));
          return;
        }
      }

      setState((s) => {
        if (s.result) return s;
        return { ...s, isRunning: false, error: "Agent stream ended without a result" };
      });
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("AgentCore invocation failed:", err);
      setState((s) => ({ ...s, isRunning: false, error: err.message || "AgentCore invocation failed" }));
    }
  }, []);

  return { ...state, invoke, reset };
}
