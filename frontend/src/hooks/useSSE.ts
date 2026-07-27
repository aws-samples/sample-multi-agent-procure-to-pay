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

type SSEHandler = (data: any) => void;

export function useSSE(_eventType: string, _handler: SSEHandler) {
  // No-op — SSE endpoint removed
  useEffect(() => {}, []);
}
