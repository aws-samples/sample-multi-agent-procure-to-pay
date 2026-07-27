# ARIA P2P — Architecture, Data Flow & Agent Workflows

> Single reference for system architecture, data flow, and agent orchestration.

---

## 1. System Architecture

```mermaid
graph TB
    subgraph Users["External Users"]
        Browser["React SPA<br/>(Tailwind + Lucide)"]
    end

    subgraph CDN["Edge Layer"]
        CF["CloudFront + WAFv2"]
        S3["S3 Bucket<br/>(static assets)"]
    end

    subgraph Auth["Authentication"]
        Cognito["Cognito User Pool<br/>+ Identity Pool"]
    end

    subgraph API["API Layer"]
        APIGW["API Gateway v2 (HTTP)<br/>JWT Authorizer"]
        APILambda["API Lambda<br/>(FastAPI + Mangum)<br/>Chat · Dashboard · Decisions<br/>Lifecycle · Config"]
        AdapterLambda["ERP Adapter Lambda<br/>(FastAPI, VPC)<br/>Canonical P2P REST API"]
    end

    subgraph Agents["AI Agent Layer"]
        direction TB
        AC1["Requisition Agent"]
        AC2["Sourcing Agent"]
        AC3["PO Management Agent"]
        AC4["Receiving Agent"]
        AC5["Invoice Matching Agent"]
        AC6["Payment Agent"]
        AC7["Workflow Agent"]
        AC8["Chat Agent"]
    end

    subgraph Gateway["MCP Gateway Layer"]
        MCP["AgentCore MCP Gateway<br/>(StreamableHTTP + SigV4)"]
        Cedar["Cedar Policy Engine<br/>(Role-based tool RBAC)"]
    end

    subgraph AI["Amazon Bedrock"]
        LLM["Claude Sonnet 4"]
        Guard["Guardrail<br/>(Automated Reasoning)"]
        Memory["AgentCore Memory<br/>(conversation context)"]
        CodeInt["Code Interpreter<br/>(spend analytics)"]
    end

    subgraph Storage["State & Secrets"]
        DDB["DynamoDB<br/>document-lifecycle<br/>invoice-jobs<br/>simulation-state"]
        SM["Secrets Manager<br/>(per-user API keys)"]
        TX["Amazon Textract<br/>(invoice extraction)"]
    end

    subgraph Simulation["Simulation Engine"]
        EB["EventBridge<br/>(3 schedules)"]
        SimLambda["Simulation Lambda<br/>(demand + GR + invoice)"]
    end

    subgraph ERP["ERP System of Record"]
        ERPNext["ERPNext v15<br/>(EC2 + Docker)"]
        RDS["RDS MariaDB"]
        Redis["ElastiCache Redis"]
    end

    subgraph FutureERP["Adapter Pattern<br/>(future ERPs)"]
        SAP["SAP S/4HANA"]
        Infor["Infor M3/LN"]
        Workday["Workday"]
    end

    Browser -->|"HTTPS + JWT"| CF
    CF --> APIGW
    CF --> S3
    Browser -->|"SRP Auth"| Cognito
    Cognito -->|"Validates JWT"| APIGW
    APIGW -->|"/api/*"| APILambda
    APIGW -->|"/api/erp/*"| AdapterLambda
    APILambda -->|"SSE Proxy"| Agents
    Agents -->|"MCP Protocol"| MCP
    MCP --> Cedar
    Cedar -->|"Lambda invoke"| AdapterLambda
    AdapterLambda -->|"REST + per-user keys"| ERPNext
    AdapterLambda --> SM
    Agents -->|"InvokeModel"| LLM
    Agents -->|"ApplyGuardrail"| Guard
    Agents -.->|"InvokeMemory"| Memory
    Agents -.->|"CodeInterpreter"| CodeInt
    APILambda --> DDB
    AdapterLambda --> TX
    EB --> SimLambda
    SimLambda -->|"POST /api/erp/*"| AdapterLambda
    ERPNext --> RDS
    ERPNext --> Redis
    AdapterLambda -.->|"Same interface"| FutureERP

    style Users fill:#ffffff,stroke:#333,color:#000
    style CDN fill:#dbeafe,stroke:#3b82f6,color:#000
    style Auth fill:#dbeafe,stroke:#3b82f6,color:#000
    style API fill:#dbeafe,stroke:#3b82f6,color:#000
    style Agents fill:#fee2e2,stroke:#ef4444,color:#000
    style Gateway fill:#fef3c7,stroke:#f59e0b,color:#000
    style AI fill:#f3e8ff,stroke:#a855f7,color:#000
    style Storage fill:#dbeafe,stroke:#3b82f6,color:#000
    style Simulation fill:#ffedd5,stroke:#f97316,color:#000
    style ERP fill:#dcfce7,stroke:#22c55e,color:#000
    style FutureERP fill:#f9fafb,stroke:#9ca3af,color:#000,stroke-dasharray: 5 5
```

The flow moves top-down from the user's browser through CloudFront and API Gateway into two Lambda functions — one for operational API routes (dashboard, decisions, chat) and one for ERP data access (the canonical adapter). The 8 AgentCore Runtimes sit in a separate compute layer and access ERP data exclusively through the MCP Gateway, which enforces Cedar RBAC policies before invoking the adapter Lambda. The dashed lines to Bedrock services (Memory, Code Interpreter) indicate optional/async integrations. The ERPNext box at the bottom is the single source of truth; the dashed line to SAP/Infor/Workday shows the adapter pattern allows future ERP swaps without changing agent code.

---

## 2. Data Flow Diagrams

### 2a. User Request Flow (Browser → ERP)

```mermaid
sequenceDiagram
    actor User as Maria Chen (Requester)
    participant FE as React SPA
    participant CF as CloudFront
    participant GW as API Gateway
    participant API as API Lambda
    participant Adapter as ERP Adapter Lambda
    participant SM as Secrets Manager
    participant ERP as ERPNext

    User->>FE: "Show me pending requisitions"
    FE->>CF: GET /api/erp/requisitions?status=pending
    Note over FE: Authorization: Bearer <Cognito JWT>
    CF->>GW: Forward request
    GW->>GW: Validate JWT against Cognito
    GW->>Adapter: Route /api/erp/* → Adapter Lambda
    Note over GW,Adapter: X-P2P-User-Email: demo+maria@example.com
    Adapter->>SM: Get API key for maria's email
    SM-->>Adapter: api_key + api_secret
    Adapter->>ERP: GET /api/resource/Material Request
    Note over Adapter,ERP: Authorization: token key:secret
    ERP-->>Adapter: Material Requests (as Maria)
    Adapter-->>FE: Canonical JSON response
    FE-->>User: Rendered table of pending PRs
```

Every request from the browser carries a Cognito JWT. API Gateway validates the token and routes ERP data requests (`/api/erp/*`) to the Adapter Lambda. The adapter extracts `X-P2P-User-Email` from the request header, looks up that user's API key/secret pair in Secrets Manager, and authenticates to ERPNext *as that user*. This means ERPNext's native permissions apply — Maria can only see what her Purchase User role allows. The adapter translates ERPNext's internal field names (e.g., `material_request_type`) to canonical names (e.g., `request_type`) before returning the response.

---

### 2b. Agent Tool Call Flow (AgentCore → ERP)

```mermaid
sequenceDiagram
    participant Agent as Requisition Agent<br/>(AgentCore Runtime)
    participant LLM as Claude Sonnet 4<br/>(Bedrock)
    participant MCP as MCP Gateway<br/>(StreamableHTTP)
    participant Cedar as Cedar Policy Engine
    participant Adapter as ERP Adapter Lambda
    participant ERP as ERPNext

    Agent->>LLM: "Analyze PR MAT-REQ-00042"
    LLM-->>Agent: Tool call: erp___get_requisition(requisition_id="MAT-REQ-00042")
    Agent->>MCP: SigV4-signed MCP tool call
    MCP->>Cedar: Authorize: IamEntity × erp___get_requisition × Gateway
    Cedar-->>MCP: PERMIT (IAM agents get full read/write)
    MCP->>Adapter: Lambda Invoke (tool_name="get_requisition", params={...})
    Adapter->>ERP: GET /api/resource/Material Request/MAT-REQ-00042
    ERP-->>Adapter: Requisition data
    Adapter-->>MCP: Canonical JSON
    MCP-->>Agent: Tool result
    Agent->>LLM: Continue reasoning with requisition data
    LLM-->>Agent: Tool call: erp___list_purchase_orders(...)
    Note over Agent,LLM: Agent makes 4-6 tool calls per analysis
```

AgentCore Runtimes use the Strands SDK to run Claude Sonnet 4.6. When the LLM decides it needs ERP data, it emits a tool call. The agent sends this via MCP protocol (StreamableHTTP) to the AgentCore MCP Gateway, which first checks Cedar policies to determine if this principal (IAM entity for server-side agents, OAuth user for browser-initiated calls) is allowed to call this tool. If permitted, the Gateway invokes the Adapter Lambda with the tool name and parameters. The adapter routes to the correct ERPNext API endpoint. Note: agents never touch ERPNext directly — every data access is mediated by Cedar authorization.

---

### 2c. Invoice Processing — Two Paths

There are two ways invoices enter the system: **electronic** (simulation or ERP-native) and **PDF upload** (human-driven via the ARIA frontend).

#### Path A: Electronic Invoices (Simulation / ERP-native)

```mermaid
flowchart LR
    subgraph Simulation["Simulation Engine"]
        SIM["Simulation Lambda<br/>(EventBridge)"]
    end

    subgraph ERP["ERPNext"]
        INV_REC["Purchase Invoice<br/>(electronic record)"]
    end

    subgraph Agent["Agent Processing"]
        IMA["Invoice Matching<br/>Agent"]
    end

    subgraph Match["Three-Way Match"]
        INV["Invoice"]
        PO["Purchase Order"]
        GR["Goods Receipt"]
        Result["MATCHED /<br/>DISCREPANCY"]
    end

    SIM -->|"① Create invoice via<br/>canonical API"| INV_REC
    INV_REC -->|"② Trigger"| IMA
    IMA --> INV
    IMA --> PO
    IMA --> GR
    INV --> Result
    PO --> Result
    GR --> Result

    style Simulation fill:#dbeafe,stroke:#3b82f6
    style ERP fill:#dcfce7,stroke:#22c55e
    style Agent fill:#fef3c7,stroke:#f59e0b
    style Match fill:#dcfce7,stroke:#22c55e
```

**How this works**: The simulation Lambda (or any ERP integration) creates invoices as **electronic records** directly in ERPNext via the canonical adapter API. No PDF, no Textract — the structured data already exists. The Invoice Matching Agent then performs the three-way match: Invoice vs. PO vs. Goods Receipts.

#### Path B: PDF Invoice Upload (Frontend)

```mermaid
flowchart LR
    subgraph Upload["ARIA Frontend"]
        USER["AP Clerk uploads<br/>vendor PDF invoice"]
    end

    subgraph Extract["Document AI"]
        S3["S3 Bucket<br/>p2p-documents"]
        TX["Amazon Textract<br/>AnalyzeExpense"]
    end

    subgraph Process["Create + Match"]
        Adapter["ERP Adapter<br/>(create invoice)"]
        ERP["ERPNext<br/>(invoice record)"]
        IMA["Invoice Matching<br/>Agent"]
    end

    USER -->|"① Upload PDF"| S3
    S3 -->|"② Extract"| TX
    TX -->|"③ Structured data<br/>(vendor, amount, lines)"| Adapter
    Adapter -->|"④ Create invoice"| ERP
    ERP -->|"⑤ Trigger"| IMA

    style Upload fill:#dbeafe,stroke:#3b82f6
    style Extract fill:#fee2e2,stroke:#ef4444
    style Process fill:#fef3c7,stroke:#f59e0b
```

**How this works**: When an AP clerk receives a physical or emailed PDF invoice, they upload it through the ARIA frontend. The PDF lands in S3, Amazon Textract's AnalyzeExpense API extracts structured data (vendor name, invoice number, dates, line items, amounts), and the adapter creates the invoice in ERPNext. From there, the same Invoice Matching Agent performs the three-way match. Textract confidence tiers (AUTO_ACCEPT ≥95%, REVIEW 80-95%, MANUAL <80%) determine whether the extraction needs human review before creating the ERP record.

---

## 3. Agent Workflows vs. Standalone Analysis

ARIA has **two modes** of agent execution. Understanding the difference is critical.

### Workflow Mode (Orchestrated Pipeline)

The **Workflow Agent** chains three agents in sequence with an approval gate. This is the primary procurement flow.

```mermaid
stateDiagram-v2
    [*] --> CREATED: User creates Material Request

    state "Step 1: Requisition Analysis" as S1 {
        [*] --> ValidateItems: Check item catalog
        ValidateItems --> CheckDuplicates: Search recent PRs
        CheckDuplicates --> ComparePricing: Historical PO prices
        ComparePricing --> CheckBudget: Cost center budget
        CheckBudget --> RiskScore: Calculate LOW/MED/HIGH
        RiskScore --> [*]
    }

    CREATED --> S1: Workflow starts
    S1 --> REJECTED: Agent recommends REJECT

    state "Step 2: Sourcing Evaluation" as S2 {
        [*] --> ListSuppliers: Get all active suppliers
        ListSuppliers --> HistoricalData: PO history + performance
        HistoricalData --> ScoreSuppliers: Price 35% · Delivery 30%<br/>Quality 20% · Capacity 15%
        ScoreSuppliers --> RecommendVendor: Highest score wins
        RecommendVendor --> [*]
    }

    S1 --> S2: Analysis complete

    state "Approval Gate (deterministic)" as Gate {
        [*] --> Evaluate
        Evaluate --> AUTO_APPROVE: LOW risk AND total ≤ $5K
        Evaluate --> ESCALATE: Everything else
        ESCALATE --> HUMAN_DECIDES
        HUMAN_DECIDES --> APPROVED: Human approves
        HUMAN_DECIDES --> REJECTED: Human rejects
    }

    S2 --> Gate: Both steps complete

    state "Step 3: PO Generation" as S3 {
        [*] --> GetRequisition: Retrieve PR details
        GetRequisition --> ValidateSupplier: Confirm supplier active
        ValidateSupplier --> CheckConsolidation: Look for bundling opportunities
        CheckConsolidation --> CreatePO: erp___create_purchase_order
        CreatePO --> [*]
    }

    Gate --> S3: Approved
    Gate --> REJECTED: Human rejects
    S3 --> PO_CREATED: PO created in ERPNext
    PO_CREATED --> [*]
    REJECTED --> [*]
```

**How the workflow works**: Steps 1 (Requisition Analysis) and 2 (Sourcing Evaluation) **always run to completion** before the approval gate evaluates. This is intentional — the approver needs both the risk assessment and vendor recommendation to make an informed decision. The approval gate is **deterministic** (code in `_post_process()`, not LLM-decided): LOW risk + ≤$5K = auto-approve; everything else = escalate to human. If a human approves later, the workflow **resumes** at Step 3 (PO Generation) without re-running Steps 1-2. The system also supports auto-reject: if the Requisition Agent recommends REJECT (e.g., duplicate, unknown items), the workflow terminates immediately — sourcing is skipped.

---

### Standalone Analysis Mode

Each agent can also run independently for **read-only analysis**.

```mermaid
flowchart TB
    subgraph Trigger["User Trigger"]
        UI["Frontend: 'Run Analysis' button"]
    end

    subgraph Execute["Agent Execution"]
        API["API Lambda<br/>POST /api/agents/requisition/stream"]
        Runtime["AgentCore Runtime<br/>(requisition agent)"]
        MCP["MCP Gateway → ERP tools"]
    end

    subgraph Record["Record Results"]
        DDB["DynamoDB lifecycle<br/>runs[] array, type=analysis"]
    end

    subgraph NoSideEffects["What Does NOT Happen"]
        NoStatus["❌ No status transitions"]
        NoApprove["❌ No auto-approve/reject"]
        NoPO["❌ No PO creation"]
    end

    UI -->|"document_id + user_email"| API
    API -->|"SSE proxy"| Runtime
    Runtime -->|"Read-only tool calls"| MCP
    Runtime -->|"Result JSON"| DDB
    Runtime -->|"Stream events"| UI

    style Trigger fill:#e3f2fd,stroke:#1565c0
    style Execute fill:#fce4ec,stroke:#c62828
    style Record fill:#fff8e1,stroke:#f57f17
    style NoSideEffects fill:#ffebee,stroke:#c62828,stroke-dasharray: 5 5
```

**How standalone mode works**: A user clicks "Run Analysis" on a Material Request from the UI. This invokes a single agent (e.g., Requisition, Sourcing, Invoice Matching) without triggering the full workflow pipeline. The agent performs the same analysis using the same MCP tools, but the result is recorded in the lifecycle `runs[]` array as `type: "analysis"` — no status transitions, no approval gates, no ERP writes. This is useful for re-analysis, what-if scenarios, or auditing a past decision.

| Mode | Trigger | Writes to ERP? | Changes Status? | Use Case |
|------|---------|---------------|----------------|----------|
| **Workflow** | `auto_start_workflow` from chat, or resume API | YES (creates PO) | YES (full lifecycle) | Primary procurement flow |
| **Standalone** | "Run Analysis" button in UI | NO (read-only) | NO | Re-analysis, what-if, audit |

---

## 4. Three Safety Layers

```mermaid
flowchart TD
    REQ(["User / Agent makes a tool call"])

    subgraph L1["Layer 1: Cedar Policy Engine"]
        direction LR
        Q1{{"CAN this principal<br/>call this tool?"}}
        E1["WHERE: MCP Gateway<br/>WHEN: Before tool executes<br/>WHAT: Role-based access control"]
    end

    subgraph L2["Layer 2: Approval Rules"]
        direction LR
        Q2{{"HOW should the<br/>agent reason?"}}
        E2["WHERE: System prompts + _post_process<br/>WHEN: During agent reasoning<br/>WHAT: Thresholds and scoring weights"]
    end

    subgraph L3["Layer 3: Bedrock Guardrail"]
        direction LR
        Q3{{"DID the agent<br/>follow the rules?"}}
        E3["WHERE: ApplyGuardrail API<br/>WHEN: After agent output<br/>WHAT: Automated Reasoning validation"]
    end

    OUT(["Result returned to user"])

    REQ --> L1
    L1 -->|"Tool permitted"| L2
    L2 -->|"Agent produces output"| L3
    L3 --> OUT

    style L1 fill:#e8f4fd,stroke:#1a73e8
    style L2 fill:#fef7e0,stroke:#e37400
    style L3 fill:#fce8e6,stroke:#d93025
```

**How the three layers work together**: They operate at different points in the request lifecycle and catch different failure modes. **Layer 1 (Cedar)** is infrastructure-level authorization — like IAM for tools. It runs *before* any tool executes and prevents, for example, a requester from calling `create_payment`. **Layer 2 (Approval Rules)** guides the LLM's reasoning — thresholds ($5K auto-approve, $50K escalation) and scoring weights (price 35%, delivery 30%) are injected into system prompts. The deterministic `_post_process()` function enforces hard limits as a safety net. **Layer 3 (AR Guardrail)** validates the agent's final output against a formal policy model — catching cases where the LLM hallucinates an approval that violates business rules. Cedar prevents unauthorized *actions*; rules guide *thinking*; guardrails validate *output*.

---

## 5. Agent Inventory

```mermaid
flowchart LR
    subgraph Pipeline["Procure-to-Pay Pipeline"]
        direction LR
        PR["Material<br/>Request"] --> REQ["Requisition<br/>Agent"]
        REQ --> SRC["Sourcing<br/>Agent"]
        SRC --> PO["PO Management<br/>Agent"]
        PO --> RCV["Receiving<br/>Agent"]
        RCV --> INV["Invoice Matching<br/>Agent"]
        INV --> PAY["Payment<br/>Agent"]
    end

    subgraph Orchestration["Orchestration"]
        WF["Workflow Agent<br/>(chains 1→2→3)"]
        CHAT["Chat Agent<br/>(conversational)"]
    end

    WF -.->|"Chains"| REQ
    WF -.->|"Chains"| SRC
    WF -.->|"Chains"| PO
    CHAT -.->|"Can invoke"| Pipeline

    style Pipeline fill:#f5f5f5,stroke:#333
    style Orchestration fill:#fff8e1,stroke:#f57f17
```

**How the agents relate**: Six domain agents form a linear pipeline corresponding to the P2P lifecycle stages. The **Workflow Agent** orchestrates the first three (Requisition → Sourcing → PO) with an approval gate between sourcing and PO generation. The **Receiving**, **Invoice Matching**, and **Payment** agents run independently — triggered by downstream events (goods delivery, invoice arrival). The **Chat Agent** provides a conversational interface that can read from any pipeline stage and create Material Requests for requesters.

| Agent | Input | Output | Key MCP Tools |
|-------|-------|--------|---------------|
| **Requisition** | `requisition_id` | Risk score + APPROVE/REJECT/ESCALATE | `get_requisition`, `list_items`, `list_requisitions`, `list_purchase_orders`, `get_budget_status` |
| **Sourcing** | `requisition_id` | Ranked supplier scores + recommendation | `list_suppliers`, `list_purchase_orders`, `get_supplier_performance` |
| **PO Management** | `requisition_id` + `supplier_id` | Created PO in ERPNext | `get_requisition`, `create_purchase_order` |
| **Receiving** | `order_id` | Quantity/timing validation | `get_purchase_order`, `list_receipts` |
| **Invoice Matching** | `invoice_id` | MATCHED or DISCREPANCY with line details | `get_invoice`, `get_purchase_order`, `list_receipts` |
| **Payment** | `invoice_id` | PAY_AT_DISCOUNT / PAY_AT_NET / HOLD | `get_invoice`, `list_payments` |
| **Workflow** | `document_id` | Chains Req→Sourcing→[Gate]→PO | All of the above |
| **Chat** | Natural language | Text + optional PR creation | All read tools + `create_requisition` |

---

## 6. Lifecycle Data Model

```mermaid
erDiagram
    LIFECYCLE {
        string document_id PK "MAT-MR-2026-00042"
        string document_type "PR"
        string status "PO_CREATED"
        string po_order_id "PUR-ORD-2026-00018"
        datetime created_at
        datetime updated_at
    }
    RUN {
        string id PK "uuid"
        string parent_id FK "links to workflow run"
        string type "workflow | analysis | decision"
        string agent "requisition | sourcing | po_management"
        string status "completed | pending_approval | failed"
        string recommendation "APPROVE | vendor name"
        float confidence "0.0 - 1.0"
        json result "full agent output"
        string action "AI_APPROVED | HUMAN_REJECTED"
        string decided_by "AI_AGENT | sarah.johnson"
    }
    LIFECYCLE ||--o{ RUN : "runs[] array"
```

**How the data model works**: Every Material Request gets one DynamoDB record in the `document-lifecycle` table. The `runs[]` array contains all agent activity as a **tree structure** — the workflow run is the root, with child entries for each agent step and decision. The `parent_id` field links children to their workflow parent, enabling the frontend to render an expandable tree view. Decision entries record both AI-driven outcomes (auto-approve, auto-escalate) and human resolutions (approve, reject), with `decided_by` providing the audit trail. The `result` field stores the complete agent JSON output — findings, reasoning, vendor scores — so no information is lost.

**Example record**:
```json
{
  "document_id": "MAT-MR-2026-00042",
  "status": "PO_CREATED",
  "po_order_id": "PUR-ORD-2026-00018",
  "runs": [
    { "id": "uuid-1", "type": "workflow", "agent": "workflow", "status": "completed" },
    { "id": "uuid-2", "parent_id": "uuid-1", "type": "analysis", "agent": "requisition",
      "recommendation": "APPROVE", "confidence": 0.92 },
    { "id": "uuid-3", "parent_id": "uuid-1", "type": "analysis", "agent": "sourcing",
      "recommendation": "Midwest Fasteners Inc", "result": { "vendor_score": 87 } },
    { "id": "uuid-4", "parent_id": "uuid-1", "type": "decision",
      "action": "AI_APPROVED", "decided_by": "AI_AGENT" },
    { "id": "uuid-5", "parent_id": "uuid-1", "type": "analysis", "agent": "po_management",
      "result": { "created_order_id": "PUR-ORD-2026-00018" } }
  ]
}
```
