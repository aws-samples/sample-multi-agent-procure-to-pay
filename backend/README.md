# Backend

Python backend for the P2P Agentic Platform. Two Lambda functions + AgentCore container.

## Components

### Adapter Lambda (`adapters/canonical_api.py`)
ERP-agnostic REST API deployed behind API Gateway at `/api/erp/*`. Translates canonical P2P operations to ERPNext REST calls via the adapter pattern.

- **`adapters/models.py`** — Canonical Pydantic models (shared contract)
- **`adapters/erp_adapter_base.py`** — Abstract interface (22 methods)
- **`adapters/erpnext/`** — ERPNext implementation (client, adapter, field_maps, OAuth)

### API Lambda (`main.py`)
FastAPI app for operational endpoints (not ERP data):

- `/api/agents/chat` — Chat agent (Strands + MCP Gateway)
- `/api/dashboard/metrics` — Aggregated pipeline metrics (calls adapter API)
- `/api/decisions/` — Agent audit trail (DynamoDB)
- `/api/errors/` — Agent error logs (DynamoDB)
- `/api/config/` — Approval rules and agent configuration (YAML)
- `/api/admin/` — Health check and demo reset
- `/api/lifecycle/` — Document lifecycle state machine

### AgentCore Runtime (`agentcore_app.py`)
Single container image for all 8 agents. `AGENT_NAME` env var selects behavior. Each agent uses MCP Gateway for ERP data access and Strands SDK for LLM reasoning.

**Agents**: Requisition, Sourcing, PO Management, Receiving, Invoice Matching, Payment, Workflow (chained), Chat (streaming).

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────────────┐
│ API Lambda   │     │ AgentCore    │     │ Adapter Lambda    │
│ (FastAPI)    │     │ Runtime ×8   │     │ (Canonical API)   │
│              │     │              │     │                   │
│ /api/chat    │     │ Bedrock LLM  │────→│ ERPAdapterBase    │
│ /api/dash    │     │ MCP Gateway  │     │  └─ERPNextAdapter │
│ /api/decide  │     │ Code Interp  │     │    └─field_maps   │
│ /api/errors  │     │ Memory       │     │    └─client       │
│ /api/config  │     │ Guardrails   │     │    └─oauth        │
└──────┬───────┘     └──────────────┘     └────────┬──────────┘
       │                                           │
       ▼                                           ▼
  DynamoDB (3 tables)                         ERPNext (VPC)
```

## Auth Flow

1. Cognito JWT → API Gateway validates
2. `X-P2P-User-Email` header propagated to adapter
3. Adapter selects per-user ERPNext API key (or falls back to service account)

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | API Lambda entrypoint (FastAPI + Mangum) |
| `agentcore_app.py` | AgentCore Runtime entrypoint (all agents) |
| `config.py` | Pydantic settings (env vars + .env) |
| `Dockerfile` | Shared container image for agents |
| `requirements.txt` | Python dependencies |

## Local Dev

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Tests

```bash
python -m pytest tests/ -v
```

## Related

- [Architecture & Data Flow](../docs/ARCHITECTURE.md) — Full system architecture, data flow diagrams, agent workflows
- [Code Review](../docs/CODE_REVIEW.md) — Deep review of all backend code
