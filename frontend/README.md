# Frontend — ARIA

> **A**gentic **R**easoning for **I**ntelligent **A**utomation

React + TypeScript SPA for the P2P Agentic Platform. Role-based UI with real-time agent streaming.

<!-- GIF PLACEHOLDER: Replace with a screen recording of the frontend UI -->
<!-- Recommended: Record navigation through different roles — requester chat, approver dashboard, AP clerk invoices -->
![ARIA Frontend](../docs/assets/aria-frontend.gif)
> ⚠️ **TODO**: Replace with a GIF showing the UI across different user roles (requester chat, approver dashboard, AP clerk invoice matching).

## Tech Stack

| Technology | Purpose |
|-----------|---------|
| React 18 | UI framework |
| TypeScript | Type safety |
| Vite | Build tool + dev server |
| TailwindCSS | Utility-first styling |
| Lucide React | Icon library |
| amazon-cognito-identity-js | Cognito auth |
| @aws-sdk/client-bedrock-agent-runtime | AgentCore invocation (SigV4) |

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Entry Portal | `/` | Role-based landing with quick stats |
| Agent Chat | `/chat` | Conversational AI assistant (streaming) |
| Dashboard | `/dashboard` | Procurement KPIs and metrics |
| Requisitions | `/requisitions` | Material request pipeline |
| Sourcing | `/sourcing` | Supplier evaluation results |
| Purchase Orders | `/purchase-orders` | PO management |
| Goods Receipts | `/goods-receipts` | Receiving validation |
| Invoices | `/invoices` | Invoice matching + 3-way match |
| Payments | `/payments` | Payment scheduling |
| Command Center | `/command-center` | Agent monitoring |
| Decisions | `/decisions` | AI decision audit trail |
| Configuration | `/configuration` | Approval rules viewer |
| Architecture | `/architecture` | Interactive architecture diagram |

## Roles

| Role | Access |
|------|--------|
| `requester` | Chat (create PRs), Requisitions, Dashboard |
| `approver` | All pipeline pages, Decisions, Command Center |
| `ap_clerk` | Invoices, Payments, Receipts, Dashboard |
| `procurement` | All pipeline pages, Sourcing, POs |
| `executive` | Dashboard, Decisions, Configuration |
| `admin` | Everything |

## Auth Flow

```
User → Login (Cognito SRP) → ID Token + Access Token
     → API calls: Authorization: Bearer <idToken>
     → ERP calls: + X-P2P-User-Email header
     → AgentCore: SigV4 via Cognito Identity Pool
```

## Local Dev

```bash
npm install
cp .env.example .env  # Edit with your API URL and Cognito IDs
npm run dev            # http://localhost:5173
```

## Build

```bash
npm run build          # Outputs to dist/
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | API Gateway URL |
| `VITE_COGNITO_POOL_ID` | Cognito User Pool ID |
| `VITE_COGNITO_CLIENT_ID` | Cognito App Client ID |
| `VITE_COGNITO_REGION` | AWS Region (default: us-east-1) |
| `VITE_IDENTITY_POOL_ID` | Cognito Identity Pool ID (for AgentCore SigV4) |

## Key Components

| Component | File | Description |
|-----------|------|-------------|
| `Shell` | `components/ui/Shell.tsx` | Page layout wrapper |
| `AgentProgress` | `components/AgentProgress.tsx` | Real-time agent step display |
| `AgentReasoning` | `components/AgentReasoning.tsx` | Agent decision breakdown |
| `ThreeWayMatch` | `components/ThreeWayMatch.tsx` | Invoice matching visualization |
| `NotificationBell` | `components/NotificationBell.tsx` | Agent completion alerts |

## Related

- [Root README](../README.md) — Full project documentation
- [Code Review](../CODE_REVIEW.md) — Frontend-related findings
- [Backend README](../backend/README.md) — API and agent documentation
