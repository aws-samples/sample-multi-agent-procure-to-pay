// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Server-Sent Events hook — stub.
 *
 * The /api/events/stream endpoint has been removed (event data now comes
 * from ERPNext directly). This stub keeps any existing consumers from
 * breaking — the handler simply never fires.
 */

import { useEffect } from "react";

type SSEHandler = (data: unknown) => void;

export function useSSE(eventType: string, handler: SSEHandler) {
  // No-op — SSE endpoint removed. Params are retained for API compatibility
  // with existing/future consumers; referenced here so they are not "unused".
  void eventType;
  void handler;
  useEffect(() => {}, []);
}
