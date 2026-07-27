<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# Local development harness

Run the full ARIA stack on your machine without a CDK deploy. The harness
emulates the AWS services that have local equivalents and shims the AgentCore
APIs that don't — **only Bedrock model calls go to real AWS**.

> **Design principle (borrowed from a sibling project):** local-ness is *entirely
> configuration*. Nothing in `backend/` branches on "local". Delete the `local/`
> directory (plus a tiny, dormant-in-production seam in `frontend/src/agentcore.ts`
> and `frontend/index.html`) and the tree is identical to a normal deploy.

## What runs where

| Deployed (AWS) | Local substitute |
|---|---|
| DynamoDB tables | moto (in-memory), provisioned by `scripts/init_aws.py` |
| S3 document bucket | moto |
| Secrets Manager (ERPNext creds) | moto |
| AgentCore Gateway (MCP tools → ERP) | `shims/mcp_gateway_shim.py` (FastMCP over the canonical API) |
| AgentCore Runtime (7 agents) | `shims/agentcore_shim.py` + `shims/run_agent.py` (`app.run(port=N)`) |
| AgentCore Memory (chat history) | `shims/agentcore_shim.py` (in-process event store) |
| Browser → AgentCore (SigV4) | `shims/agent_proxy_shim.py` (plain HTTP; no Cognito) |
| Cognito auth | guest mode (`window.ARIA_CONFIG.localMode`) |
| ERPNext (system of record) | `infra/docker/docker-compose.local-test.yaml` |
| **Bedrock (Claude)** | **real AWS** — the one real dependency |

The switch is botocore-native: the supervisor sets `AWS_ENDPOINT_URL_<SERVICE>`
for DynamoDB/S3/Secrets Manager/`bedrock-agentcore`, and leaves
`bedrock-runtime` unset so agent model calls hit real Bedrock. Application code
just calls `boto3.client(...)` with no endpoint argument.

## Prerequisites

- **AWS credentials with Bedrock access** and **Claude Sonnet model access
  enabled** in your region (see the main README "Bedrock model access" step).
  Everything else is emulated; Bedrock is real, so this is required.
- Python via the repo venv (`~/.venv`), Node/npm for the SPA, Docker for ERPNext.
- Python deps: `moto`, `uvicorn`, `starlette`, `httpx`, `fastmcp` (already in the
  backend/utilities requirements + venv).

## Quick start

```bash
cp local/env.example local/.env        # fill in AWS_ACCESS_KEY_ID / SECRET / (SESSION_TOKEN)

make -C local erpnext                   # 1) start local ERPNext (docker compose)
#   Open http://localhost:8080 and complete the Frappe setup wizard ONCE:
#   Company "Apex Manufacturing Group" (abbr AMG), USD/United States,
#   warehouse "Stores - AMG". (Same one-time step as a real deploy.)

make -C local seed                      # 2) (optional) seed demo suppliers/items/requisitions
make -C local up                        # 3) emulators + shims + 7 agents + backend (foreground)
make -C local ui                        # 4) in a second terminal: the SPA (Vite on :5173)
```

Then open the Vite URL (http://localhost:5173). The SPA runs in guest mode and
routes agent invocations through the local proxy → agent → real Bedrock, with
ERP data from your local ERPNext.

`make -C local up` runs in the foreground and multiplexes every process's logs
with a `[name]` prefix; Ctrl-C stops them all. ERPNext and the SPA are long-lived
and run separately (targets above).

## Ports

| Port | Process |
|---|---|
| 5173 | SPA (Vite dev server) |
| 8000 | Backend (`uvicorn main:app`) |
| 8001 | Canonical API (in-process under the MCP gateway shim) |
| 8002 | MCP gateway shim (`/mcp`) |
| 8003 | Agent proxy shim (browser-facing) |
| 8080 | ERPNext (docker compose) |
| 8081–8087 | The seven agent processes |
| 9000 | AgentCore shim (runtime + memory) |
| 5100 | moto (DynamoDB + S3 + Secrets Manager) |

Override any of these in `local/.env` (see `local/config/harness_env.py`).

## How the pieces fit

- `config/harness_env.py` — single source of truth for ports and the
  `AWS_ENDPOINT_URL_*` / app env every process inherits.
- `supervisor.py` — starts moto, provisions it, then launches the shims, the
  seven agents, and the backend; streams all logs; Ctrl-C tears everything down.
- `shims/` — the AWS-API stand-ins (see the table above). Each is also runnable
  standalone for debugging.
- `scripts/init_aws.py` — creates tables/bucket/secret matching the CDK schema.
- `scripts/seed_local.py` — drives the canonical `utilities/scripts/04`+`05` seed
  scripts against local ERPNext (the scripts stay in `utilities/` — they're the
  shared runbook for real deploys too).

## Limitations

- **CodeInterpreter** (used by payment/sourcing/invoice agents for math) is an
  AgentCore resource with no local equivalent; those agents fall back gracefully
  (the code already guards it with try/except) and run without it locally.
- **Textract** invoice OCR has no local emulator, but extraction is Bedrock-first
  (real, works here); Textract is only a fallback if Bedrock fails.
- Guest mode bypasses Cognito, so per-user ERP identity / RBAC nuances differ
  from a real deploy.
