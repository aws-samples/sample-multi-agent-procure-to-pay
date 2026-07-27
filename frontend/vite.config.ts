// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Local-dev proxy: when ARIA_LOCAL_PROXY=1 (set by `make -C local ui`), the Vite
// dev server forwards the SPA's API calls to the local harness — /api/erp/* to
// the canonical API shim, everything else under /api to the backend. This only
// affects the dev server; production builds are served statically and never use
// it. Ports mirror local/config/harness_env.py.
const localProxy = process.env.ARIA_LOCAL_PROXY === '1'
const backendPort = process.env.ARIA_BACKEND_PORT || '8000'
const canonicalPort = process.env.ARIA_CANONICAL_API_PORT || '8001'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: localProxy
    ? {
        proxy: {
          // Order matters: the more specific /api/erp rule is declared first.
          '/api/erp': { target: `http://127.0.0.1:${canonicalPort}`, changeOrigin: true },
          '/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
        },
      }
    : undefined,
})
