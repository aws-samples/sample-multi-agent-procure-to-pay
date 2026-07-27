# Agents — AI Procurement Specialists

Eight autonomous agents that power the P2P workflow. Each runs on AgentCore Runtime (ARM64 container) using Claude Sonnet 4 via the Strands SDK.

## Agent Inventory

| Agent | File | Deployment | Tools | Description |
|-------|------|------------|-------|-------------|
| **Requisition** | `requisition_agent.py` | AgentCore Runtime | MCP Gateway | Validates PRs, risk-scores, recommends APPROVE/REJECT/ESCALATE |
| **Sourcing** | `sourcing_agent.py` | AgentCore Runtime | MCP Gateway + Code Interpreter | Evaluates suppliers on 4-criteria weighted scorecard |
| **PO Management** | `po_management_agent.py` | AgentCore Runtime | MCP Gateway | Generates POs from approved PRs + selected supplier |
| **Receiving** | `receiving_agent.py` | AgentCore Runtime | MCP Gateway | Validates goods receipts against POs (handles partial deliveries) |
| **Invoice Matching** | `invoice_matching_agent.py` | AgentCore Runtime | MCP Gateway + Code Interpreter | Three-way match: Invoice vs PO vs Goods Receipt |
| **Payment** | `payment_agent.py` | AgentCore Runtime | MCP Gateway + Code Interpreter | Optimizes payment timing for early discount capture |
| **Workflow** | (in `agentcore_app.py`) | AgentCore Runtime | MCP Gateway | Chains Requisition → Sourcing → PO with human-in-the-loop |
| **Chat** | `chat_agent.py` | Lambda (sync) | MCP Gateway or REST | Conversational assistant for all roles |

## Decision Boundaries

| Agent | Auto-Approve | Escalate | Reject |
|-------|-------------|----------|--------|
| Requisition | risk=LOW, total≤$5K | risk=HIGH or total>$50K | Invalid items/supplier |
| Invoice Matching | confidence≥0.9, all lines MATCH | Missing PO/GR, large variance | — |
| Payment | Discount annualized rate>15% | Amount>$100K, duplicate | — |

## Prompt Architecture

Each agent has a system prompt with:
1. **Company context** — Apex Manufacturing Group, ~20 suppliers, industrial materials
2. **Available tools** — MCP Gateway tool descriptions
3. **Step-by-step process** — Explicit analysis workflow (5-7 steps)
4. **Output format** — JSON schema with required fields
5. **Critical rules** — Hard constraints (never guess, show math, cite tools)

## Tool Access

Agents access ERP data exclusively through MCP Gateway:
```
Agent → MCP Client (SigV4) → AgentCore Gateway → Cedar Policy → Adapter Lambda → ERPNext
```

## Adding a New Agent

1. Create `new_agent.py` with `SYSTEM_PROMPT` (or `_build_system_prompt()`)
2. Add agent name to `AGENTS` dict in CDK stack (`infra/lib/p2p-agentic-stack.ts`)
3. Add prompt selection to `_get_system_prompt()` in `agentcore_app.py`
4. Add user-facing prompt to `_get_prompt()` in `agentcore_app.py`
5. Build and push updated container image
6. Deploy: `npx cdk deploy P2PAgenticStack`
