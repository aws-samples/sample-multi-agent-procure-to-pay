# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
AgentCore Runtime entrypoint for P2P agents.

Streams real-time progress events as the agent works using async generator.
The AGENT_NAME env var determines which agent runs.

Architecture:
  - ERP data access: MCP tools via AgentCore Gateway (canonical P2P API)
  - Local computation: budget check, contract lookup, risk scoring
  - Memory: AgentCore Memory for cross-session context
"""

import os
import json
import logging
import time
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

logging.basicConfig(level=logging.INFO, format="%(name)s — %(message)s")
logger = logging.getLogger("p2p.agentcore")

app = BedrockAgentCoreApp()

AGENT_NAME = os.environ.get("AGENT_NAME", "requisition")
GATEWAY_ENDPOINT = os.environ.get("GATEWAY_ENDPOINT", "")
GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")

# Tool descriptions are in utils/progress_hooks.py (shared with ProgressBridge)
from utils.progress_hooks import TOOL_DESCRIPTIONS

AGENT_LABELS = {
    "requisition": "Requisition Agent",
    "sourcing": "Sourcing Agent",
    "po_management": "PO Management Agent",
    "receiving": "Receiving Agent",
    "invoice_matching": "Invoice Matching Agent",
    "payment": "Payment Agent",
}


def _build_mcp_client():
    """Build MCP client for AgentCore Gateway tools (ERP data access)."""
    from utils.mcp_client import build_mcp_client
    return build_mcp_client(GATEWAY_ENDPOINT)


def _build_local_tools(agent_name: str) -> list:
    """Build local computation tools (not ERP data — budget, contracts, scoring)."""
    tools = []

    # Budget check is now via MCP Gateway (erp__get_budget_status) — no local tool needed

    if agent_name in ("sourcing",):
        try:
            from agents.sourcing_agent import build_contract_tools
            tools.extend(build_contract_tools())
        except Exception:
            logger.warning("Sourcing contract tools unavailable")

    if agent_name in ("po_management",):
        try:
            from agents.sourcing_agent import build_contract_tools as src_contract_tools
            tools.extend(src_contract_tools())
        except Exception:
            logger.warning("Sourcing contract tools unavailable for PO management")
        try:
            from agents.po_management_agent import build_contract_tools as po_contract_tools
            tools.extend(po_contract_tools())
        except Exception:
            logger.warning("PO contract tools unavailable")

    return tools


# Agents that get Code Interpreter for computational analysis
CODE_INTERPRETER_AGENTS = {"payment", "sourcing", "invoice_matching"}


def _build_code_interpreter(agent_name: str):
    """Build Code Interpreter tool for agents that need computational capabilities.

    Uses the AgentCore CodeInterpreter resource via the Strands tools package.
    Enables precise financial math, scorecard calculations, and variance analysis.
    """
    if agent_name not in CODE_INTERPRETER_AGENTS:
        return None

    try:
        from strands_tools.code_interpreter import AgentCoreCodeInterpreter

        region = os.environ.get("AWS_REGION_NAME", "us-east-1")
        ci = AgentCoreCodeInterpreter(region=region)
        logger.info(f"[{agent_name}] Code Interpreter tool enabled")
        return ci.code_interpreter
    except Exception as e:
        logger.warning(f"[{agent_name}] Code Interpreter unavailable: {e}")
        return None


def _get_system_prompt(agent_name: str) -> str:
    """Get system prompt for an agent. Builds dynamic prompts if needed."""
    if agent_name == "requisition":
        from agents.requisition_agent import SYSTEM_PROMPT
        return SYSTEM_PROMPT
    elif agent_name == "sourcing":
        from agents.sourcing_agent import SYSTEM_PROMPT, _build_system_prompt
        return SYSTEM_PROMPT or _build_system_prompt()
    elif agent_name == "po_management":
        from agents.po_management_agent import SYSTEM_PROMPT
        return SYSTEM_PROMPT
    elif agent_name == "receiving":
        from agents.receiving_agent import SYSTEM_PROMPT
        return SYSTEM_PROMPT
    elif agent_name == "invoice_matching":
        from agents.invoice_matching_agent import SYSTEM_PROMPT, _build_system_prompt
        return SYSTEM_PROMPT or _build_system_prompt()
    elif agent_name == "payment":
        from agents.payment_agent import SYSTEM_PROMPT
        return SYSTEM_PROMPT
    return ""


def _get_prompt(agent_name: str, document_id: str, user_email: str = "") -> str:
    # Identity clause — ensures every tool call includes user_email for per-user ERP auth
    identity = f' Pass user_email="{user_email}" in every ERP tool call.' if user_email else ""
    prompts = {
        "requisition": f"Analyze purchase requisition requisition_id={document_id}.{identity} Use the tools to retrieve the requisition details, check items, suppliers, look for duplicates, and compare historical pricing. Then provide your recommendation as JSON.",
        "invoice_matching": f"Perform a three-way match on invoice invoice_id={document_id}.{identity} Retrieve the invoice, the purchase order, and any goods receipts. Compare each line item across all three documents. Return your match result as JSON.",
        "sourcing": f"Evaluate vendors for purchase requisition requisition_id={document_id}.{identity} Analyze all suppliers using historical purchase order and receipt data. Recommend the best supplier with scoring and justification.",
        "po_management": f"Generate a purchase order for requisition requisition_id={document_id}.{identity} Retrieve the requisition, validate items, check for consolidation opportunities.",
        "receiving": f"Validate goods receipts for purchase order order_id={document_id}.{identity} Check quantities, delivery timing, and flag any issues.",
        "payment": f"Analyze payment scheduling for invoice invoice_id={document_id}.{identity} Determine optimal payment timing considering discount opportunities.",
    }
    return prompts.get(agent_name, f"Process document {document_id}")


def _validate_with_guardrail(response_text: str) -> dict:
    """Validate agent reasoning against procurement policy guardrail (Automated Reasoning).

    Returns:
        dict with keys:
            valid (bool): True if no policy violations found
            action (str): "NONE" or "GUARDRAIL_INTERVENED"
            findings (list): AR findings with result/rule/explanation
    """
    if not GUARDRAIL_ID:
        return {"valid": True, "action": "NONE", "findings": []}

    try:
        import boto3
        bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"),
        )
        response = bedrock.apply_guardrail(
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION,
            source="OUTPUT",
            content=[{"text": {"text": response_text}}],
        )

        action = response.get("action", "NONE")
        ar_findings = []
        for assessment in response.get("assessments", []):
            ar = assessment.get("automatedReasoningPolicy", {})
            for finding in ar.get("findings", []):
                ar_findings.append({
                    "result": finding.get("result"),
                    "rule": finding.get("rule", ""),
                    "explanation": finding.get("explanation", ""),
                })

        return {
            "valid": action == "NONE",
            "action": action,
            "findings": ar_findings,
        }
    except Exception as e:
        logger.warning("Guardrail validation failed: %s", e)
        return {"valid": True, "action": "ERROR", "findings": [], "error": str(e)}


AGENT_DOCUMENT_TYPES = {
    "requisition": "PR",
    "invoice_matching": "INVOICE",
    "payment": "PAYMENT",
    "sourcing": "SOURCING",
    "po_management": "PO",
    "receiving": "RECEIPT",
}


def _post_process(agent_name: str, parsed: dict) -> dict:
    """Apply deterministic business rules as a second line of defense.

    Cedar Policy handles authorization, Automated Reasoning validates
    against procurement rules. This adds lightweight deterministic checks.
    """
    if agent_name == "requisition":
        total = float(parsed.get("total_amount", 0) or 0)
        risk = parsed.get("risk_level", "")
        recommendation = parsed.get("recommendation", "")

        # Budget FAIL → force HIGH risk + ESCALATE (check first, overrides everything)
        for finding in parsed.get("findings", []):
            if finding.get("check", "").lower().startswith("budget") and finding.get("status") == "FAIL":
                parsed["risk_level"] = "HIGH"
                parsed["auto_approved"] = False
                parsed["recommendation"] = "ESCALATE"
                return parsed

        # HIGH risk or over $50K → always escalate to human
        if risk == "HIGH" or total > 50000:
            parsed["auto_approved"] = False
            if recommendation != "REJECT":
                parsed["recommendation"] = "ESCALATE"
        # LOW/MEDIUM risk, agent recommends APPROVE, under $5K → auto-approve
        elif risk in ("LOW", "MEDIUM") and total <= 5000 and recommendation == "APPROVE":
            parsed["auto_approved"] = True
            parsed["recommendation"] = "APPROVE"
        # Everything else (MEDIUM risk ESCALATE, etc.) → defer to human
        else:
            parsed["auto_approved"] = False
    return parsed


@app.entrypoint
async def invoke(payload):
    """Stream progress events as the agent works, then yield the final result."""
    document_id = payload.get("document_id", "")
    user_email = payload.get("user_email", "")

    # Workflow agent — chains requisition → sourcing → PO
    if AGENT_NAME == "workflow":
        resume_from = payload.get("resume_from", "")
        async for event in _run_workflow(document_id, user_email, resume_from):
            yield event
        return

    agent_label = AGENT_LABELS.get(AGENT_NAME, AGENT_NAME)
    logger.info(f"[{AGENT_NAME}] Invoking for document: {document_id}, user: {user_email}")
    start_time = time.time()

    # --- Duplicate standalone agent guard ---
    # Resolve tracking doc and check for running entry before starting
    _agent_run_id = ""
    _tracking_doc_id = document_id
    if document_id and AGENT_NAME in ("receiving", "invoice_matching", "payment"):
        from services.lifecycle import is_agent_active, get_lifecycle_by_po, add_run_entry as _add_run, update_run_status as _update_status

        po_id = payload.get("order_id", "")
        if po_id:
            mr_lifecycle = get_lifecycle_by_po(po_id)
            if mr_lifecycle:
                _tracking_doc_id = mr_lifecycle["document_id"]

        active_check = is_agent_active(_tracking_doc_id, AGENT_NAME)
        if active_check["active"] and not active_check["stale"]:
            logger.warning(f"[{AGENT_NAME}] Duplicate blocked for {document_id} (run: {active_check['run_id']})")
            yield json.dumps({
                "type": "error",
                "error": "DUPLICATE_AGENT",
                "message": f"{agent_label} is already running for this document. Please wait for it to complete.",
                "agent": AGENT_NAME,
            }) + "\n"
            return
        elif active_check["active"] and active_check["stale"]:
            old_run_id = active_check.get("run_id", "")
            if old_run_id:
                _update_status(_tracking_doc_id, old_run_id, "failed")
            logger.warning(f"[{AGENT_NAME}] Stale agent run for {document_id} (run={old_run_id}) — cleaned up")

        # Record a "running" entry so future invocations can detect it
        _agent_run_id = _add_run(
            document_id=_tracking_doc_id,
            entry_type="analysis",
            agent=AGENT_NAME,
            status="running",
        )

    yield json.dumps({"type": "progress", "step": f"{agent_label} starting analysis", "agent": AGENT_NAME}) + "\n"

    # Build tools: MCP (ERP data) + local (computation)
    mcp_client = _build_mcp_client()
    local_tools = _build_local_tools(AGENT_NAME)

    if not mcp_client:
        logger.error(f"[{AGENT_NAME}] GATEWAY_ENDPOINT not set — MCP tools unavailable")
        yield json.dumps({"type": "error", "error": "MCP Gateway not configured", "agent": AGENT_NAME}) + "\n"
        return
    all_tools = [mcp_client, *local_tools]

    # Add Code Interpreter for agents that need computational analysis
    ci_tool = _build_code_interpreter(AGENT_NAME)
    if ci_tool:
        all_tools.append(ci_tool)

    # Tool descriptions are built dynamically by the Agent when it starts the MCP client.
    # Do NOT call mcp_client.start()/stop() here — it conflicts with Agent's own lifecycle.

    system_prompt = _get_system_prompt(AGENT_NAME)
    prompt = _get_prompt(AGENT_NAME, document_id, user_email)
    response_text = ""

    try:
        from config import settings
        from utils.progress_hooks import ProgressBridge

        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            streaming=False,
        )

        bridge = ProgressBridge(AGENT_NAME)
        agent = Agent(
            model=model,
            tools=all_tools,
            system_prompt=system_prompt,
            hooks=[bridge.hook_provider],
        )

        # Run agent in thread, stream per-tool progress events in real-time
        async for event_line in bridge.run(agent, prompt):
            yield event_line
        result = bridge.result

        if hasattr(result, 'message') and result.message:
            for block in result.message.get("content", []):
                if isinstance(block, dict) and "text" in block:
                    response_text += block["text"]
                elif isinstance(block, str):
                    response_text += block
        if not response_text:
            response_text = str(result)
        tools_used = []

        # Parse JSON from response
        json_str = response_text
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]

        try:
            parsed = json.loads(json_str.strip())
        except json.JSONDecodeError:
            parsed = {"raw_response": response_text, "confidence": 0.0}

        # Standalone analysis is READ-ONLY — no auto_approve, no decisions.
        # Record in runs[] for history (visible in MR modal tree) but not as a decision.
        if document_id and isinstance(parsed, dict) and not parsed.get("error"):
            try:
                from services.lifecycle import add_run_entry, get_lifecycle_by_po, update_run_entry

                rec = parsed.get("recommendation", parsed.get("match_result", parsed.get("validation_result", "")))
                conf = _safe_float(parsed.get("confidence", 0))
                reasoning = parsed.get("reasoning", parsed.get("summary", ""))

                if _agent_run_id:
                    # Update the "running" entry created at invocation start
                    update_run_entry(
                        document_id=_tracking_doc_id,
                        run_id=_agent_run_id,
                        status="completed",
                        recommendation=str(rec),
                        confidence=conf,
                        summary=str(reasoning) if reasoning else "",
                        result=parsed,
                    )
                else:
                    # Agents without duplicate tracking — create entry as before
                    tracking_doc_id = document_id
                    if AGENT_NAME in ("receiving", "invoice_matching", "payment"):
                        po_id = payload.get("order_id", "")
                        if not po_id:
                            po_id = (parsed.get("order_id", "")
                                     or parsed.get("purchase_order", "")
                                     or parsed.get("po_number", ""))
                        if po_id:
                            mr_lifecycle = get_lifecycle_by_po(po_id)
                            if mr_lifecycle:
                                tracking_doc_id = mr_lifecycle["document_id"]
                                logger.info(f"[{AGENT_NAME}] Tracking run under MR {tracking_doc_id} (PO: {po_id})")

                    add_run_entry(
                        document_id=tracking_doc_id,
                        entry_type="analysis",
                        agent=AGENT_NAME,
                        status="completed",
                        recommendation=str(rec),
                        confidence=conf,
                        summary=str(reasoning) if reasoning else "",
                        result=parsed,
                    )
            except Exception as e:
                logger.warning(f"[{AGENT_NAME}] Failed to record standalone run: {e}")
        logger.info(f"[{AGENT_NAME}] completed (read-only), keys: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")

    except Exception as e:
        import traceback
        logger.error(f"[{AGENT_NAME}] failed: {e}\n{traceback.format_exc()}")
        parsed = {"error": str(e), "reasoning": f"Agent error: {e}", "confidence": 0.0}
        tools_used = []
        # Mark running entry as failed
        if _agent_run_id:
            try:
                from services.lifecycle import update_run_entry
                update_run_entry(_tracking_doc_id, _agent_run_id, status="failed")
            except Exception:
                pass  # nosec B110 -- best-effort lifecycle update inside an outer error handler

    # Validate agent reasoning against procurement policy (Automated Reasoning)
    ar_validation = _validate_with_guardrail(response_text)
    if ar_validation.get("findings"):
        logger.info(f"[{AGENT_NAME}] AR findings: {len(ar_validation['findings'])}")

    duration = round(time.time() - start_time, 1)
    metrics = {"total_duration_s": duration}

    yield json.dumps({
        "type": "result",
        "agent": AGENT_NAME,
        "document_id": document_id,
        "result": parsed,
        "ar_validation": ar_validation,
        "tools_used": tools_used,
        "progress_steps": [],
        "metrics": metrics,
    }) + "\n"


def _safe_float(val) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


async def _run_workflow(document_id: str, user_email: str = "", resume_from: str = ""):
    """Run the full P2P workflow: Requisition → Sourcing → [Approval Gate] → PO.

    Steps 1+2 always run to completion. The approval gate evaluates AFTER both:
    - AUTO-APPROVE: LOW risk AND total <= $5K → proceed to PO automatically
    - DEFER TO HUMAN: everything else → pause at PENDING_APPROVAL
    - AUTO-REJECT: agent recommends REJECT → terminal after Step 1

    Supports resume_from="po_generation" to skip Steps 1+2 after human approval.
    """
    from agents.p2p_workflow import _extract_text, _parse_json
    from config import settings
    from utils.progress_hooks import ProgressBridge
    from services.lifecycle import (
        set_status, record_po_created, add_run_entry, update_run_status,
        get_latest_workflow_run_id, Status,
    )

    model = BedrockModel(model_id=settings.bedrock_model_id, streaming=False)

    mcp_client = _build_mcp_client()
    steps_log = []
    identity = f' Pass user_email="{user_email}" in every ERP tool call.' if user_email else ""

    logger.info(f"[workflow] Starting P2P workflow for {document_id}, user: {user_email}, resume_from: {resume_from}")

    # --- Duplicate workflow guard ---
    if not resume_from:
        from services.lifecycle import is_workflow_active
        active_check = is_workflow_active(document_id)
        if active_check["active"] and not active_check["stale"]:
            logger.warning(f"[workflow] Duplicate blocked for {document_id} (status: {active_check['status']}, run: {active_check['run_id']})")
            yield json.dumps({
                "type": "error",
                "error": "DUPLICATE_WORKFLOW",
                "message": f"A workflow is already running for {document_id} (step: {active_check.get('current_step') or active_check['status']}). Please wait for it to complete.",
                "agent": "workflow",
                "status": active_check.get("status", ""),
            }) + "\n"
            return
        elif active_check["active"] and active_check["stale"]:
            # Stale workflow — clean up and allow re-trigger
            old_run_id = active_check.get("run_id", "")
            if old_run_id:
                update_run_status(document_id, old_run_id, "failed")
            set_status(document_id, Status.FAILED, "stale_workflow_cleanup")
            logger.warning(f"[workflow] Stale workflow for {document_id} (run={old_run_id}) — cleaned up, allowing re-trigger")

    if not mcp_client:
        logger.error("[workflow] GATEWAY_ENDPOINT not set — MCP tools unavailable")
        yield json.dumps({"type": "error", "error": "MCP Gateway not configured", "agent": "workflow"}) + "\n"
        return

    # Track variables across steps
    req_result = {}
    src_result = {}
    recommendation = "APPROVE"
    risk = "UNKNOWN"
    confidence = 0
    auto_approved = False
    vendor = {}
    vendor_id = ""
    vendor_name = "unknown"
    vendor_score = "N/A"
    workflow_run_id = ""

    if resume_from != "po_generation":
        yield json.dumps({"type": "progress", "step": "Starting P2P workflow", "agent": "workflow"}) + "\n"
        # --- Create workflow run entry ---
        workflow_run_id = add_run_entry(document_id, "workflow", agent="workflow", status="running")

        # --- Step 1: Sourcing Evaluation (runs first to identify suppliers) ---
        set_status(document_id, Status.SOURCING, "sourcing")
        yield json.dumps({"type": "progress", "step": "Step 1: Evaluating suppliers...", "agent": "workflow"}) + "\n"

        try:
            from utils.progress_hooks import ProgressBridge

            src_tools = [mcp_client]
            src_tools.extend(_build_local_tools("sourcing"))

            src_bridge = ProgressBridge("sourcing")
            src_agent = Agent(model=model, tools=src_tools, system_prompt=_get_system_prompt("sourcing"), hooks=[src_bridge.hook_provider])
            src_prompt = (
                f"Evaluate suppliers for purchase requisition requisition_id={document_id}.{identity} "
                f"Analyze all suppliers and recommend the best with scoring."
            )
            async for evt in src_bridge.run(src_agent, src_prompt):
                yield evt
            src_response = src_bridge.result
            src_text = _extract_text(src_response)
            src_result = _parse_json(src_text)
            if not isinstance(src_result, dict):
                src_result = {"raw_response": str(src_text), "recommended_vendor": {}}
            steps_log.append({"agent": "sourcing", "result": src_result})
        except Exception as e:
            logger.error(f"[workflow] Step 1 (sourcing) failed: {e}")
            update_run_status(document_id, workflow_run_id, "failed")
            yield json.dumps({"type": "result", "agent": "workflow", "document_id": document_id, "result": {"error": str(e), "workflow": True, "workflow_status": "FAILED"}}) + "\n"
            return

        # Check for agent-reported errors
        if src_result.get("error"):
            logger.warning(f"[workflow] Step 1 agent error: {src_result['error']} (code: {src_result.get('error_code')})")

        # Extract vendor info
        vendor = src_result.get("recommended_vendor") or src_result.get("recommended_supplier") or {}
        vendor_name = (vendor.get("supplier_name") or vendor.get("name") or
                       vendor.get("supplier_id") or vendor.get("supplier") or "unknown") if isinstance(vendor, dict) else "unknown"
        vendor_score = (vendor.get("score") or vendor.get("total_score") or
                        vendor.get("overall_score") or "N/A") if isinstance(vendor, dict) else "N/A"
        vendor_id = ""
        if isinstance(vendor, dict):
            vendor_id = vendor.get("supplier_id", "") or vendor.get("supplier_name", "") or vendor.get("id", "") or vendor.get("name", "")
        if not vendor_id and isinstance(src_result, dict):
            vendor_id = src_result.get("recommended_supplier_id", "") or src_result.get("recommended_supplier", "")

        # Collect supplier IDs for the requisition agent's risk assessment
        supplier_ids_for_req = []
        if vendor_id:
            supplier_ids_for_req.append(vendor_id)
        split_award_data = src_result.get("split_award") if isinstance(src_result, dict) else None
        if split_award_data and isinstance(split_award_data, list):
            for alloc in split_award_data:
                sid = alloc.get("supplier_id", "")
                if sid and sid not in supplier_ids_for_req:
                    supplier_ids_for_req.append(sid)

        # Record Step 1 in unified runs[]
        src_reasoning = src_result.get("reasoning", "") if isinstance(src_result, dict) else ""
        add_run_entry(document_id, "analysis", agent="sourcing",
                      parent_id=workflow_run_id, recommendation=vendor_name,
                      confidence=_safe_float(vendor_score) / 100 if str(vendor_score).replace(".", "").isdigit() else 0,
                      summary=src_reasoning,
                      result={
                          "vendor_id": vendor_id or vendor_name,
                          "vendor_name": vendor_name,
                          "vendor_score": _safe_float(vendor_score),
                          "reasoning": src_reasoning,
                          **(src_result if isinstance(src_result, dict) else {}),
                      })

        set_status(document_id, Status.SOURCING_COMPLETE, "sourcing_complete")
        yield json.dumps({"type": "progress", "step": f"Step 1 complete: Recommended {vendor_name} (Score: {vendor_score}/100)", "agent": "workflow"}) + "\n"

        if not vendor_id:
            add_run_entry(document_id, "decision", parent_id=workflow_run_id,
                          action="FAILED", decided_by="AI_AGENT", status="failed",
                          justification="No vendor identified by sourcing agent")
            update_run_status(document_id, workflow_run_id, "failed")
            yield json.dumps({
                "type": "result", "agent": "workflow", "document_id": document_id,
                "result": {
                    "status": "STOPPED_AT_SOURCING_NO_VENDOR",
                    "steps": steps_log, "recommendation": "ESCALATE",
                    "risk_level": "UNKNOWN", "confidence": 0,
                    "reasoning": "",
                    "findings": [],
                    "auto_approved": False, "recommended_vendor": vendor,
                    "workflow": True, "workflow_status": "FAILED",
                },
                "tools_used": [], "progress_steps": ["sourcing"], "metrics": {},
            }) + "\n"
            return

        # --- Step 2: Requisition Analysis (with supplier IDs from sourcing) ---
        set_status(document_id, Status.ANALYZING, "requisition")
        yield json.dumps({"type": "progress", "step": "Step 2: Analyzing requisition — checking items, pricing, budget...", "agent": "workflow"}) + "\n"

        try:
            req_tools = [mcp_client]
            req_tools.extend(_build_local_tools("requisition"))
            req_bridge = ProgressBridge("requisition")
            req_agent = Agent(model=model, tools=req_tools, system_prompt=_get_system_prompt("requisition"), hooks=[req_bridge.hook_provider])

            # Build prompt with supplier IDs from sourcing for risk assessment
            req_prompt = (
                f"Analyze purchase requisition requisition_id={document_id}.{identity} "
                f"Use the tools to retrieve the requisition details, check items, suppliers, "
                f"look for duplicates, and compare historical pricing. "
            )
            if supplier_ids_for_req:
                req_prompt += (
                    f"The Sourcing Agent has pre-selected these supplier(s) for this requisition: "
                    f"{json.dumps(supplier_ids_for_req)}. "
                    f"Factor supplier reliability and track record into your risk assessment. "
                )
            req_prompt += "Then provide your recommendation as JSON."

            async for evt in req_bridge.run(req_agent, req_prompt):
                yield evt
            req_response = req_bridge.result
            req_text = _extract_text(req_response)
            req_result = _parse_json(req_text)
            if not isinstance(req_result, dict):
                req_result = {"raw_response": str(req_text), "confidence": 0.0}

            req_result = _post_process("requisition", req_result)
            steps_log.append({"agent": "requisition", "result": req_result})
        except Exception as e:
            logger.error(f"[workflow] Step 2 (requisition) failed: {e}")
            update_run_status(document_id, workflow_run_id, "failed")
            yield json.dumps({"type": "result", "agent": "workflow", "document_id": document_id, "result": {"error": str(e), "steps": steps_log, "workflow": True, "workflow_status": "FAILED"}}) + "\n"
            return

        # Check for agent-reported errors (error field from structured output)
        if req_result.get("error"):
            logger.warning(f"[workflow] Step 2 agent error: {req_result['error']} (code: {req_result.get('error_code')})")
            if req_result.get("recommendation") not in ("ESCALATE", "REJECT"):
                req_result["recommendation"] = "ESCALATE"

        recommendation = req_result.get("recommendation", "ESCALATE")
        risk = req_result.get("risk_level", "UNKNOWN")
        confidence = req_result.get("confidence", 0)
        auto_approved = req_result.get("auto_approved", False)

        try:
            confidence_pct = int(float(confidence) * 100)
        except (TypeError, ValueError):
            confidence_pct = 0

        # Record Step 2 in unified runs[]
        reasoning_text = req_result.get("reasoning", "")
        add_run_entry(document_id, "analysis", agent="requisition",
                      parent_id=workflow_run_id, recommendation=recommendation,
                      confidence=_safe_float(confidence),
                      summary=reasoning_text,
                      result=req_result)

        yield json.dumps({"type": "progress", "step": f"Step 2 complete: {recommendation} (risk: {risk}, confidence: {confidence_pct}%)", "agent": "workflow"}) + "\n"

        # --- AUTO-REJECT: If requisition agent recommends REJECT ---
        if recommendation == "REJECT":
            add_run_entry(document_id, "decision", parent_id=workflow_run_id,
                          action="AI_REJECTED", decided_by="AI_AGENT", status="rejected",
                          justification=f"Agent recommended rejection: {reasoning_text[:200]}")
            update_run_status(document_id, workflow_run_id, "rejected")
            set_status(document_id, Status.REJECTED, "requisition")
            yield json.dumps({
                "type": "result", "agent": "workflow", "document_id": document_id,
                "result": {
                    "status": "REJECTED",
                    "steps": steps_log,
                    "recommendation": "REJECT",
                    "risk_level": risk,
                    "confidence": confidence,
                    "reasoning": reasoning_text,
                    "findings": req_result.get("findings", []),
                    "auto_approved": False,
                    "workflow": True,
                    "workflow_status": "REJECTED",
                },
                "tools_used": [], "progress_steps": ["sourcing", "requisition"], "metrics": {},
            }) + "\n"
            return

        # ═══ APPROVAL GATE (after Steps 1+2 both complete) ═══
        # 5 possible outcomes: AI_APPROVED, AI_REJECTED (above), AI_ESCALATED,
        #                      HUMAN_APPROVED, HUMAN_REJECTED (from frontend)
        if auto_approved:
            # AI_APPROVED: LOW risk AND total <= $5K
            add_run_entry(document_id, "decision", parent_id=workflow_run_id,
                          action="AI_APPROVED", decided_by="AI_AGENT", status="approved",
                          justification=f"Auto-approved: {risk} risk, ${req_result.get('total_amount', 0):,.0f} total")
            set_status(document_id, Status.APPROVED, "approval_gate")
            yield json.dumps({"type": "progress", "step": f"Auto-approved ({risk} risk, ${req_result.get('total_amount', 0):,.0f}) — proceeding to PO generation", "agent": "workflow"}) + "\n"
            # Fall through to Step 3
        else:
            # AI_ESCALATED: deferred to human for approval/rejection
            add_run_entry(document_id, "decision", parent_id=workflow_run_id,
                          action="AI_ESCALATED", decided_by="AI_AGENT",
                          status="pending_approval",
                          justification=f"Escalated to human: {risk} risk, ${req_result.get('total_amount', 0):,.0f} total")
            update_run_status(document_id, workflow_run_id, "pending_approval")
            set_status(document_id, Status.PENDING_APPROVAL, "approval_gate")
            yield json.dumps({"type": "progress", "step": f"Analysis and sourcing complete — awaiting your decision", "agent": "workflow"}) + "\n"
            yield json.dumps({
                "type": "result", "agent": "workflow", "document_id": document_id,
                "result": {
                    "status": "AWAITING_APPROVAL",
                    "steps": steps_log,
                    "recommendation": recommendation,
                    "risk_level": risk,
                    "confidence": confidence,
                    "reasoning": req_result.get("reasoning", ""),
                    "findings": req_result.get("findings", []),
                    "auto_approved": False,
                    "workflow": True,
                    "workflow_status": "PENDING_APPROVAL",
                    "sourcing_result": {
                        "recommended_vendor": vendor,
                        "vendor_score": vendor_score,
                        "reasoning": src_reasoning,
                    },
                },
                "tools_used": [], "progress_steps": ["sourcing", "requisition"], "metrics": {},
            }) + "\n"
            return
    else:
        # Resuming from po_generation — Steps 1+2 already completed and human approved
        workflow_run_id = get_latest_workflow_run_id(document_id)

        # Load step data from runs[] array (single source of truth)
        from services.lifecycle import get_lifecycle
        import json as _json
        lc = get_lifecycle(document_id) or {}
        lc_runs = lc.get("runs", [])
        if isinstance(lc_runs, str):
            try:
                lc_runs = _json.loads(lc_runs)
            except (ValueError, TypeError):
                lc_runs = []

        # Find the workflow and its children
        wf_entry = None
        for r in reversed(lc_runs):
            if r.get("type") == "workflow":
                wf_entry = r
                break
        wf_id = wf_entry.get("id", "") if wf_entry else ""
        wf_children = [r for r in lc_runs if r.get("parent_id") == wf_id] if wf_id else []

        req_run = next((r for r in wf_children if r.get("agent") == "requisition"), {})
        src_run = next((r for r in wf_children if r.get("agent") == "sourcing"), {})
        req_result = req_run.get("result", {}) or {}
        src_result_data = src_run.get("result", {}) or {}

        vendor_id = src_result_data.get("vendor_id", "")
        vendor_name = src_result_data.get("vendor_name", "unknown")
        vendor_score = src_result_data.get("vendor_score", "N/A")
        recommendation = req_result.get("recommendation", req_run.get("recommendation", "APPROVE"))
        risk = req_result.get("risk_level", "UNKNOWN")
        confidence = req_result.get("confidence", req_run.get("confidence", 0))
        auto_approved = req_result.get("auto_approved", False)
        # Populate req_result for the final result payload
        req_result = req_result or {}

        # Emit synthetic progress events so the frontend stepper shows
        # checkmarks for steps 1, 2, and the approval gate
        try:
            confidence_pct = int(float(confidence) * 100)
        except (TypeError, ValueError):
            confidence_pct = 0
        yield json.dumps({"type": "progress", "step": f"Step 1 complete: Recommended {vendor_name} (Score: {vendor_score}/100)", "agent": "workflow"}) + "\n"
        yield json.dumps({"type": "progress", "step": f"Step 2 complete: {recommendation} (risk: {risk}, confidence: {confidence_pct}%)", "agent": "workflow"}) + "\n"
        yield json.dumps({"type": "progress", "step": "Human-Approved — proceeding to PO generation", "agent": "workflow"}) + "\n"

    # --- Step 3: PO Generation ---
    set_status(document_id, Status.PO_GENERATION, "po_generation")

    # Check for split award from sourcing
    split_award = src_result.get("split_award") if isinstance(src_result, dict) else None
    # Also detect split from vendor_id pattern (older sourcing output)
    if not split_award and vendor_id and "SPLIT" in str(vendor_id).upper():
        # Try to parse split from vendor_name description
        logger.info(f"[workflow] Detected SPLIT_AWARD vendor_id but no structured split_award field")

    if split_award:
        yield json.dumps({"type": "progress", "step": f"Step 3: Generating {len(split_award)} purchase orders (split award)...", "agent": "workflow"}) + "\n"
    else:
        yield json.dumps({"type": "progress", "step": "Step 3: Generating purchase order...", "agent": "workflow"}) + "\n"

    try:
        po_tools = [mcp_client]
        po_tools.extend(_build_local_tools("po_management"))

        # Build PO prompt — include split award details if present
        po_prompt = (
            f"Generate a purchase order for requisition requisition_id={document_id} "
            f"with supplier supplier_id={vendor_id}.{identity} "
            f"This requisition has been APPROVED (by human or auto-approved). "
            f"Your job is to CREATE the PO — do NOT escalate or reject. "
            f"The supplier was selected by the Sourcing Agent with a score of {vendor_score}/100. "
            f"Retrieve the requisition, validate items, and CREATE the purchase order."
        )
        if split_award:
            po_prompt += (
                f"\n\nIMPORTANT — SPLIT AWARD: The Sourcing Agent recommended splitting this "
                f"requisition across multiple suppliers. Create a SEPARATE purchase order for "
                f"each supplier. Here is the split allocation:\n"
                f"{json.dumps(split_award)}\n"
                f"Create one PO per supplier with only that supplier's items. "
                f"Return ALL created PO IDs in the created_order_ids array."
            )

        po_bridge = ProgressBridge("po_management")
        po_agent = Agent(model=model, tools=po_tools, system_prompt=_get_system_prompt("po_management"), hooks=[po_bridge.hook_provider])
        async for evt in po_bridge.run(po_agent, po_prompt):
            yield evt
        po_response = po_bridge.result
        po_text = _extract_text(po_response)
        po_result = _parse_json(po_text)
        if not isinstance(po_result, dict):
            po_result = {"raw_response": str(po_text)}
        steps_log.append({"agent": "po_management", "result": po_result})
    except Exception as e:
        logger.error(f"[workflow] Step 3 failed: {e}")
        if workflow_run_id:
            update_run_status(document_id, workflow_run_id, "failed")
        yield json.dumps({"type": "result", "agent": "workflow", "document_id": document_id, "result": {"error": str(e), "steps": steps_log, "workflow": True, "workflow_status": "FAILED"}}) + "\n"
        return

    # Record Step 3 in unified runs[]
    created_order_id = po_result.get("created_order_id", "") if isinstance(po_result, dict) else ""
    created_order_ids = po_result.get("created_order_ids") if isinstance(po_result, dict) else None
    # Normalize: if created_order_ids has entries, use the first as primary
    if created_order_ids and isinstance(created_order_ids, list) and len(created_order_ids) > 0:
        created_order_id = created_order_id or created_order_ids[0]
    elif created_order_id and not created_order_ids:
        created_order_ids = [created_order_id]

    po_error = po_result.get("error") if isinstance(po_result, dict) else None
    po_action = po_result.get("action", "UNKNOWN") if isinstance(po_result, dict) else "UNKNOWN"
    po_total = _safe_float(po_result.get("total_amount") or po_result.get("po_draft", {}).get("total_amount") or 0) if isinstance(po_result, dict) else 0

    # Detect PO agent failure: error field set, or ESCALATE action, or no created_order_id with CREATE action
    po_failed = bool(po_error) or po_action == "ESCALATE" or (po_action == "CREATE" and not created_order_id)
    if po_failed:
        logger.warning(f"[workflow] Step 3 agent error: error={po_error}, action={po_action}, created_order_id={created_order_id}")

    erp_action = f"PO_CREATED:{','.join(created_order_ids or [])}" if created_order_id and not po_failed else "NONE"

    if workflow_run_id:
        run_status = "failed" if po_failed else "completed"
        add_run_entry(document_id, "analysis", agent="po_management",
                      parent_id=workflow_run_id, recommendation=po_action,
                      summary=po_result.get("reasoning", "") if isinstance(po_result, dict) else "",
                      result={
                          "created_order_id": created_order_id,
                          "created_order_ids": created_order_ids,
                          "action": po_action,
                          "total_amount": po_total,
                          "error": po_error,
                          "error_code": po_result.get("error_code") if isinstance(po_result, dict) else None,
                          **(po_result if isinstance(po_result, dict) else {}),
                      })
        update_run_status(document_id, workflow_run_id, run_status)

    if po_failed:
        error_msg = po_error or f"PO agent returned {po_action} without creating a PO"
        yield json.dumps({"type": "progress", "step": f"PO generation failed: {error_msg}", "agent": "workflow"}) + "\n"
        yield json.dumps({
            "type": "result", "agent": "workflow", "document_id": document_id,
            "result": {
                "status": "FAILED",
                "error": error_msg,
                "error_code": po_result.get("error_code") if isinstance(po_result, dict) else None,
                "steps": steps_log,
                "recommendation": recommendation,
                "risk_level": risk,
                "confidence": confidence,
                "reasoning": req_result.get("reasoning", "") if req_result else "",
                "findings": req_result.get("findings", []) if req_result else [],
                "auto_approved": auto_approved,
                "po_result": po_result,
                "workflow": True,
                "workflow_status": "FAILED",
            },
            "tools_used": [], "progress_steps": ["sourcing", "requisition", "po_management"], "metrics": {},
        }) + "\n"
        return

    record_po_created(document_id,
        order_id=created_order_id,
        order_ids=created_order_ids,
        total_amount=po_total,
        action=po_action,
    )

    if created_order_ids and len(created_order_ids) > 1:
        ids_str = ", ".join(created_order_ids)
        yield json.dumps({"type": "progress", "step": f"Purchase Orders {ids_str} created in ERP (split award)", "agent": "workflow"}) + "\n"
    elif created_order_id:
        yield json.dumps({"type": "progress", "step": f"Purchase Order {created_order_id} created in ERP", "agent": "workflow"}) + "\n"
    else:
        yield json.dumps({"type": "progress", "step": f"PO generation complete: {po_action}", "agent": "workflow"}) + "\n"

    yield json.dumps({
        "type": "result", "agent": "workflow", "document_id": document_id,
        "result": {
            "status": "COMPLETE",
            "steps": steps_log,
            "recommendation": recommendation,
            "risk_level": risk,
            "confidence": confidence,
            "reasoning": req_result.get("reasoning", "") if req_result else "",
            "findings": req_result.get("findings", []) if req_result else [],
            "auto_approved": auto_approved,
            "recommended_vendor": vendor,
            "po_result": po_result,
            "created_order_id": created_order_id,
            "created_order_ids": created_order_ids,
            "erp_action_taken": erp_action,
            "workflow": True,
            "workflow_status": "COMPLETE",
            "workflow_steps": steps_log,
            "sourcing_result": {**src_result, "recommended_vendor": vendor} if src_result else None,
        },
        "tools_used": [], "progress_steps": ["sourcing", "requisition", "po_management"], "metrics": {},
    }) + "\n"


if __name__ == "__main__":
    app.run()
