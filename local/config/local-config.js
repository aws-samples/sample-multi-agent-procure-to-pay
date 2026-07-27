// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
//
// Runtime config injected ONLY by the local/ harness (copied to
// frontend/public/local-config.js by `make up`, gitignored there). Deployed
// builds never ship this file, so window.ARIA_CONFIG stays undefined and the
// SPA uses the normal SigV4 → AgentCore path.
//
// localMode=true routes agent calls through the local agent proxy shim and
// enables guest mode (no Cognito).
window.ARIA_CONFIG = {
  localMode: true,
  agentProxyBase: "http://127.0.0.1:8003",
  // Guest persona used when no Cognito is present. Change role to explore other
  // personas (requester, approver, ap_clerk, executive, procurement).
  demoUser: {
    username: "demo+jake@example.com",
    displayName: "Jake Rodriguez",
    email: "demo+jake@example.com",
    role: "procurement",
    department: "Procurement",
  },
};
