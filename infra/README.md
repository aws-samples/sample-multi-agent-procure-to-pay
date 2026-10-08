# Infrastructure — AWS CDK

CDK TypeScript infrastructure for the P2P Agentic Platform. Two stacks deploy the complete system.

<!-- GIF PLACEHOLDER: Replace with a screen recording of cdk deploy output -->
![CDK Deploy](../docs/assets/cdk-deploy.gif)
> ⚠️ **TODO**: Replace with a GIF showing `cdk deploy` in action with stack outputs.

## Stacks

| Stack | File | What it deploys |
|-------|------|----------------|
| `ErpNextStack` | `lib/erpnext-stack.ts` | VPC, EC2 (Docker ERPNext), RDS MariaDB, ElastiCache Redis, ALB |
| `P2PAgenticStack` | `lib/p2p-agentic-stack.ts` | Everything else (see below) |

## P2PAgenticStack Resources

### Authentication & Authorization
- **Cognito User Pool** — 6 groups (admin, procurement, approver, ap_clerk, executive, requester). Group membership is the only source of a user's role.
- **Pre Token Generation Lambda (V2)** — asserts the `p2p_role` claim on both ID and access tokens from group membership and drops the user-writable `custom:role` attribute from tokens
- **Cognito app clients** — explicit `writeAttributes` (display attributes only); users cannot write `custom:*` attributes
- **Cognito Identity Pool** — SigV4 credentials for browser → AgentCore
- **Cedar Policy Engine** — Tool-level RBAC on MCP Gateway, keyed on `p2p_role`

### Compute
- **API Lambda** — FastAPI (dashboard, chat, decisions, lifecycle)
- **Adapter Lambda** — Canonical P2P API (VPC, reaches ERPNext via private subnet)
- **Simulation Lambda** — EventBridge-triggered demand generator + event scanner
- **AgentCore Runtimes ×8** — ARM64 containers (shared ECR image, `AGENT_NAME` selects agent)

### AgentCore Services
- **MCP Gateway** — Tool registry + dispatch (MCP protocol)
- **Cedar Policy Engine** — 6 Cedar policies for role-based tool authorization
- **AgentCore Memory** — Summary + Semantic strategies (30-day TTL)
- **Code Interpreter** — Python sandbox for financial calculations

### AI Services
- **Bedrock Guardrail** — Automated Reasoning for procurement policy validation
- **Textract** — AnalyzeExpense for invoice PDF extraction

### Storage
- **DynamoDB** — 4 tables (agent-jobs, agent-errors, document-lifecycle, simulation-state)
- **S3** — Frontend assets + invoice documents
- **Secrets Manager** — ERPNext credentials (service + per-user API keys)
- **ECR** — Agent container repository

### Networking & Security
- **API Gateway v2** — HTTP API with JWT authorizer
- **CloudFront** — Frontend distribution with custom domain
- **WAFv2** — Common rules, IP reputation, rate limiting
- **Route53** — Custom domain alias (optional)
- **ACM Certificate** — TLS for custom domain (optional)

### Simulation
- **EventBridge Rule 1** — Demand Generator (every 6 hours, starts DISABLED)
- **EventBridge Rule 2** — Event Scanner (every 5 minutes, starts DISABLED)
- **SNS Topic** — Cedar policy deny alerts

## Deploy

```bash
npm install
npx cdk deploy ErpNextStack           # Deploy ERPNext first
npx cdk deploy P2PAgenticStack        # Then the platform
```

## Context Values

Set in `cdk.context.json` (copy from `cdk.context.example.json`):

| Key | Description | Example |
|-----|-------------|---------|
| `erpnextUrl` | ERPNext ALB URL | `https://erp.your-domain.example.com` |
| `hostedZoneName` | Route53 hosted zone | `your-domain.example.com` |
| `frontendDomainPrefix` | Subdomain for frontend | `aria` |

## Key Files

| File | Description |
|------|-------------|
| `lib/p2p-agentic-stack.ts` | Main platform stack |
| `lib/p2p-auth.ts` | Cognito: pool, app clients (restricted `writeAttributes`), groups, V2 pre-token trigger |
| `lib/p2p-policy.ts` | AgentCore Policy Engine loaded from the Cedar file, attached to the Gateway in ENFORCE mode |
| `lib/p2p-auth-e2e-stack.ts` | Isolated harness: Cognito + JWT-authenticated Gateway + stub target + Cedar, for the live E2E test |
| `lib/erpnext-stack.ts` | ERPNext infrastructure |
| `lib/openapi/p2p-tools.json` | MCP Gateway tool definitions |
| `lib/openapi/p2p-canonical.json` | OpenAPI spec for adapter API |
| `policies/p2p-procurement.cedar` | Cedar authorization policies (keyed on the `p2p_role` claim) |
| `lambda/pre_token_generation/handler.py` | Pre Token Generation trigger: Cognito Group -> `p2p_role` claim |
| `bin/app.ts` | CDK app entry point (ErpNextStack, P2PAgenticStack) |
| `bin/e2e.ts` | CDK app entry point for P2PAuthE2EStack only |

## Tests

```bash
# Unit: Cedar policy structure + role authorization (runs in CI).
# Evaluates policies/p2p-procurement.cedar with cedarpy against a simulated
# UpdateUserAttributes -> pre-token trigger -> Gateway tag mapping chain.
pip install -r tests/requirements.txt
python -m pytest -q tests

# End to end (needs AWS credentials; deploys an isolated stack, no ERPNext).
# Uses a throwaway user against real Cognito, a real Cognito-JWT-authenticated
# AgentCore Gateway, and the real Cedar policies: self-update custom:role
# (rejected), token claims, tools/call decisions, operator-set custom:role=admin
# still denied, group membership grants access.
pip install -r tests/e2e/requirements.txt
npm run e2e:deploy
npm run e2e:test
npm run e2e:destroy
```

## Related

- [Architecture Diagram](../docs/architecture-diagram.drawio) — Visual architecture (open in draw.io)
- [Root README](../README.md) — Full deployment guide
