# Utilities — Setup Runbook

Run these scripts **in order** to get a working ARIA demo environment. Each script is numbered — follow the sequence.

## Prerequisites

```bash
cd utilities
pip install -r requirements.txt
cp .env.example .env   # Edit with your ERPNext URL and credentials
```

Your `.env` needs (no defaults — scripts refuse to run without these):
```
ERPNEXT_URL=https://erp.your-domain.example.com
ERPNEXT_USER=Administrator
ERPNEXT_PASSWORD=<the value you set as erpnextAdminPassword in cdk.context.json>
ERPNEXT_USER_PASSWORD=<a strong demo-persona password — e.g. openssl rand -base64 24>
```

**Before you run any script** make sure both CDK stacks are fully deployed
*and* you have completed the ERPNext setup wizard (Company =
`Apex Manufacturing Group`, Warehouse = `Stores - AMG`) — see the main
[README](../README.md#deployment) for details.

## Setup Sequence

### Step 1 — Verify ERPNext is reachable

```bash
python scripts/01_verify_erpnext.py
```

Checks that ERPNext is running, the company exists, and basic API connectivity works. **Stop here if this fails** — fix your ERPNext deployment first.

### Step 2 — Create users (ERPNext + Cognito)

```bash
python scripts/02_setup_users.py
```

Creates user accounts in **both systems** from a single persona definition:
- **ERPNext**: accounts with ERP roles (Purchase User, Stock User, Accounts User, etc.)
- **Cognito**: user pool entries with app roles (requester, approver, ap_clerk, etc.)

Also creates simulation requesters (ERPNext-only) and the service account.

Options:
```bash
python scripts/02_setup_users.py --erpnext-only        # Skip Cognito (ERPNext must be reachable)
python scripts/02_setup_users.py --cognito-only         # Skip ERPNext (Cognito pool must exist)
python scripts/02_setup_users.py --delete-cognito       # Reset Cognito users first
python scripts/02_setup_users.py --pool-id us-east-1_X  # Manual Cognito pool ID
```

**Password handling.** Both ERPNext and Cognito users get the value from
`ERPNEXT_USER_PASSWORD` (set in your shell or in `utilities/.env`). Pick a
strong value — for example `openssl rand -base64 24`. The script will refuse
to run if the variable is empty.

### Step 3 — Generate API keys + store in Secrets Manager

```bash
python scripts/03_setup_erpnext_oauth.py
```

Generates API key/secret pairs for each ERPNext user and stores them in the AWS Secrets Manager secret created by CDK (`p2p-dev/erpnext-credentials`). This enables per-user ERP identity — agents act as the logged-in user, not a service account.

### Step 4 — Seed demo data

```bash
python scripts/04_seed_demo_data.py
```

Populates ERPNext with:
- **15 suppliers** (Midwest Fasteners, Valley Steel, etc.)
- **60 items** across 11 groups (Fasteners, Steel, Electrical, Safety, etc.)
- **7 purchase orders** with receipts, invoices, and payments (completed history)
- **3 pending Material Requests** (ready for agent analysis)
- **Payment terms** and **budgets** per cost center

### Step 5 — Verify demo data loaded correctly

```bash
python scripts/05_verify_demo_data.py
```

Counts documents in ERPNext and reports any missing data. Run this before proceeding — if counts are off, re-run Step 4.

---

## Maintenance Scripts

### Reset demo data (between demos)

```bash
python scripts/06_reset_demo.py
```

Clears transaction data (POs, invoices, payments) but keeps master data (suppliers, items). Re-run Step 4 after this to repopulate.

### Nuclear option (full wipe)

```bash
python scripts/07_nuke_all_data.py
```

Deletes **everything** — master data, transactions, all of it. Use when you want a completely fresh start. Re-run Steps 2-5 after this.

---

## Script Reference

| Script | Purpose | Idempotent? |
|--------|---------|------------|
| `config.py` | Shared configuration (loaded from `.env`) | N/A |
| `erpnext_client.py` | HTTP client for ERPNext REST API | N/A |
| `01_verify_erpnext.py` | Check ERPNext connectivity | ✅ |
| `02_setup_users.py` | Create users in ERPNext + Cognito | ✅ (skips existing) |
| `03_setup_erpnext_oauth.py` | Generate API keys → Secrets Manager | ✅ (regenerates) |
| `04_seed_demo_data.py` | Load demo data into ERPNext | ⚠️ (may duplicate) |
| `05_verify_demo_data.py` | Verify data counts | ✅ |
| `06_reset_demo.py` | Clear transactions, keep master data | ⚠️ (destructive) |
| `07_nuke_all_data.py` | Delete everything | ⚠️ (destructive) |

---

## Demo Personas

| User | ERPNext Role | Cognito Role | Email |
|------|-------------|-------------|-------|
| Maria Chen | Purchase User | requester | demo+maria@example.com |
| Sarah Johnson | Purchase Manager | approver | demo+sarah@example.com |
| Jake Rodriguez | Purchase User | procurement | demo+jake@example.com |
| Priya Patel | Accounts User | ap_clerk | demo+priya@example.com |
| Gary Wilson | (read-only) | executive | demo+gary@example.com |
| Carlos Mendez | Purchase User | requester | demo+carlos@example.com |
| Aisha Okafor | Purchase User | requester | demo+aisha@example.com |
| Wei Liu | Purchase User | requester | demo+wei@example.com |

---

## Simulation Engine (`simulation/`)

EventBridge-triggered Lambda that generates realistic procurement events over time:

- **Demand Generator** (every 6 hours): Creates 1-3 Material Requests from random requesters
- **GR Scanner** (every 30 min): Creates Purchase Receipts for POs awaiting delivery
- **Invoice Scanner** (every 90 min): Generates vendor invoice PDFs, uploads to S3 for Textract

Enable after setup:
```bash
aws events enable-rule --name p2p-dev-demand-generator
aws events enable-rule --name p2p-dev-gr-scanner
aws events enable-rule --name p2p-dev-invoice-scanner
```

### Local testing
```bash
python -m simulation.lambda_handler --ticks 5 --interval 10
```
