// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentCore direct invocation client.
 *
 * Calls AgentCore Runtime directly from the browser using SigV4-signed
 * requests with temporary AWS credentials from Cognito Identity Pool.
 * This avoids the 29s API Gateway timeout for long-running agent calls.
 */

import { fetchAuthSession } from "aws-amplify/auth";
import { SignatureV4 } from "@smithy/signature-v4";
import { Sha256 } from "@aws-crypto/sha256-browser";
import { HttpRequest } from "@smithy/protocol-http";

const REGION = import.meta.env.VITE_COGNITO_POOL_ID?.split("_")[0] || "us-east-1";
const ENDPOINT = `https://bedrock-agentcore.${REGION}.amazonaws.com`;

// Local-dev harness: when the runtime config (public/local-config.js, injected
// only by the local/ harness) sets localMode, agent calls are routed through a
// local proxy instead of browser SigV4 to AgentCore. This is config injection,
// not a change to agent logic — deployed builds never set window.ARIA_CONFIG.
interface AriaLocalConfig {
  localMode?: boolean;
  agentProxyBase?: string;
}
const LOCAL_CONFIG: AriaLocalConfig =
  (typeof window !== "undefined" && (window as unknown as { ARIA_CONFIG?: AriaLocalConfig }).ARIA_CONFIG) || {};

const RUNTIME_ARNS: Record<string, string> = {
  requisition: import.meta.env.VITE_AGENTCORE_REQUISITION_ARN || "",
  sourcing: import.meta.env.VITE_AGENTCORE_SOURCING_ARN || "",
  po_management: import.meta.env.VITE_AGENTCORE_PO_MANAGEMENT_ARN || "",
  receiving: import.meta.env.VITE_AGENTCORE_RECEIVING_ARN || "",
  invoice_matching: import.meta.env.VITE_AGENTCORE_INVOICE_MATCHING_ARN || "",
  payment: import.meta.env.VITE_AGENTCORE_PAYMENT_ARN || "",
  workflow: import.meta.env.VITE_AGENTCORE_WORKFLOW_ARN || "",
};

// ─── Event types ────────────────────────────────────────────────────────────

export interface AgentEvent {
  type: "progress" | "result" | "error";
  step?: string;
  agent?: string;
  tool?: string;
  document_id?: string;
  result?: any;
  tools_used?: any[];
  progress_steps?: string[];
  metrics?: Record<string, number>;
  error?: string;
  message?: string;
  status?: string;
}


// ─── Helpers ────────────────────────────────────────────────────────────────

export function isAgentCoreAvailable(agentName: string): boolean {
  // In local mode the proxy stands in for every agent runtime.
  if (LOCAL_CONFIG.localMode) return true;
  return !!RUNTIME_ARNS[agentName];
}

/** Local-mode agent invocation: plain streaming fetch to the harness proxy. */
async function _localFetch(agentName: string, body: string, sessionId: string): Promise<Response> {
  const base = LOCAL_CONFIG.agentProxyBase || "http://127.0.0.1:8003";
  return fetch(`${base}/local-agent/${agentName}/invocations`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-amzn-bedrock-agentcore-runtime-session-id": sessionId,
    },
    body,
  });
}

/** SigV4-sign a request using Cognito Identity Pool credentials. */
async function _signedFetch(url: string, body: string, sessionId: string): Promise<Response> {
  const session = await fetchAuthSession();
  const creds = session.credentials;
  if (!creds?.accessKeyId || !creds?.secretAccessKey) {
    throw new Error("No AWS credentials — Identity Pool may not be configured");
  }

  const parsedUrl = new URL(url);
  const request = new HttpRequest({
    method: "POST",
    protocol: parsedUrl.protocol,
    hostname: parsedUrl.hostname,
    port: parsedUrl.port ? Number(parsedUrl.port) : undefined,
    path: parsedUrl.pathname,
    query: Object.fromEntries(parsedUrl.searchParams),
    headers: {
      host: parsedUrl.hostname,
      "content-type": "application/json",
      "x-amzn-bedrock-agentcore-runtime-session-id": sessionId,
    },
    body,
  });

  const signer = new SignatureV4({
    service: "bedrock-agentcore",
    region: REGION,
    credentials: {
      accessKeyId: creds.accessKeyId,
      secretAccessKey: creds.secretAccessKey,
      sessionToken: creds.sessionToken,
    },
    sha256: Sha256,
  });

  const signed = await signer.sign(request);

  return fetch(url, {
    method: "POST",
    headers: signed.headers as Record<string, string>,
    body,
  });
}

function _buildUrl(arn: string): string {
  const encoded = encodeURIComponent(arn);
  return `${ENDPOINT}/runtimes/${encoded}/invocations?qualifier=DEFAULT`;
}

function _genSessionId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `session-${hex}`;
}

function _parseNdjsonLine(line: string): any | null {
  let trimmed = line.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("data: ")) trimmed = trimmed.slice(6);
  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    try { trimmed = JSON.parse(trimmed); } catch { /* not double-encoded */ }
  }
  if (!trimmed) return null;
  try { return JSON.parse(trimmed); } catch { return null; }
}

// ─── Specialized Agents — SigV4 signed, streamed ──────────────────────────

export async function* invokeAgentCore(
  agentName: string,
  documentId: string,
  extraPayload?: Record<string, string>,
): AsyncGenerator<AgentEvent> {
  const sessionId = _genSessionId();
  const body = JSON.stringify({ document_id: documentId, ...extraPayload });

  let response: Response;
  if (LOCAL_CONFIG.localMode) {
    response = await _localFetch(agentName, body, sessionId);
  } else {
    const arn = RUNTIME_ARNS[agentName];
    if (!arn) throw new Error(`No AgentCore ARN configured for agent: ${agentName}`);
    response = await _signedFetch(_buildUrl(arn), body, sessionId);
  }

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(`AgentCore HTTP ${response.status}: ${errorText || response.statusText}`);
  }

  // Stream the NDJSON response
  const reader = response.body?.getReader();
  if (!reader) {
    const text = await response.text();
    for (const line of text.split("\n")) {
      const event = _parseNdjsonLine(line);
      if (event) yield event as AgentEvent;
    }
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let foundResult = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const event = _parseNdjsonLine(line);
      if (event) {
        yield event as AgentEvent;
        if (event.type === "result") foundResult = true;
      }
    }
  }

  if (buffer.trim()) {
    const event = _parseNdjsonLine(buffer);
    if (event) {
      yield event as AgentEvent;
      if (event.type === "result") foundResult = true;
    }
  }

  if (!foundResult) {
    yield { type: "error", error: "Agent stream ended without a result" } as AgentEvent;
  }
}

