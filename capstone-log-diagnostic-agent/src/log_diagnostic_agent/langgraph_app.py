from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Annotated, Literal, TypedDict
from uuid import uuid4

from pydantic import ValidationError

from .audit import AuditLogger
from .config import Settings
from .models import (
    BranchAssessment,
    CriticAssessment,
    DiagnosisReport,
    Evidence,
    EvidenceCategory,
    EvidenceDetail,
    EvidenceSource,
    HumanReview,
    Hypothesis,
    HypothesisSet,
    IncidentRecord,
    JiraTicketResult,
    ToolResult,
)
from .orchestration_ui import OrchestrationUIReporter
from .prompts import load_agent_instructions, system_prompt
from .review import apply_human_review, eligible_for_trusted_memory
from .stores.checkpoint import checkpoint_connection_url, open_checkpointer
from .toolkit import ToolKit
from .tools.jira import DisabledJiraTicketProvider, JiraTicketProvider
from .ui_review import (
    ReviewUIError,
    build_ui_review_item,
    collect_review_in_ui,
    publish_jira_result,
)
from .validation import validate_diagnosis


CONSOLE_WIDTH = 88


def _short(value: object, limit: int = 180) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _console_phase(number: int, name: str, message: str, **details: object) -> None:
    """Print a concise, presentation-friendly view of a graph phase."""
    print("\n" + "-" * CONSOLE_WIDTH, flush=True)
    print(
        f"[{time.strftime('%H:%M:%S')}] PHASE {number:02d} | {name.upper()}",
        flush=True,
    )
    print(f"  {message}", flush=True)
    for label, value in details.items():
        if value is None or value == "" or value == []:
            continue
        print(f"  - {label.replace('_', ' ').title()}: {_short(value)}", flush=True)


def _console_detail(message: str, **details: object) -> None:
    print(f"  > {message}", flush=True)
    for label, value in details.items():
        if value is None or value == "" or value == []:
            continue
        print(f"    {label.replace('_', ' ').title()}: {_short(value)}", flush=True)


def _console_banner(incident: dict, settings: Settings, thread_id: str) -> None:
    print("\n" + "=" * CONSOLE_WIDTH, flush=True)
    print(" SIGNALDESK | LANGGRAPH LOG DIAGNOSTIC ORCHESTRATION", flush=True)
    print("=" * CONSOLE_WIDTH, flush=True)
    print(f" Incident     : {incident['incident_id']}", flush=True)
    print(f" Application  : {incident['application']}", flush=True)
    print(f" Thread       : {thread_id}", flush=True)
    print(f" Model        : {settings.llm_model}", flush=True)
    print(f" Review       : SignalDesk UI at {settings.review_ui_url}", flush=True)
    print(
        f" Safety limits: {settings.max_steps} reasoning steps | "
        f"{settings.max_tool_calls} tool calls | {settings.max_duration_seconds}s",
        flush=True,
    )
    print("=" * CONSOLE_WIDTH, flush=True)


class AgentState(TypedDict, total=False):
    messages: Annotated[list, "add_messages"]
    incident: dict
    evidence: list[dict]
    step_count: int
    tool_call_count: int
    retry_count: int
    started_at: float
    candidate_report: dict | None
    hypotheses: list[dict]
    branch_results: list[dict]
    critic: dict | None
    final_report: dict | None
    validation_errors: list[str]
    escalation_reasons: list[str]
    human_review: dict | None
    jira_ticket: dict | None
    memory_admission: dict | None


def _message_text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        chunks = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                chunks.append(str(part.get("text", "")))
            else:
                chunks.append(str(part))
        text = "".join(chunks)
    else:
        text = str(content)
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _new_evidence(result: ToolResult, existing: list[dict]) -> Evidence:
    return Evidence(
        evidence_id=f"E{len(existing) + 1}",
        source=result.source,
        category=result.category,
        summary=result.summary,
        content=result.content,
        metadata=result.metadata,
        substantive=result.substantive,
    )


def _budget_reasons(state: AgentState, settings: Settings) -> list[str]:
    reasons: list[str] = []
    if state.get("step_count", 0) >= settings.max_steps:
        reasons.append("Investigation step budget exhausted")
    if state.get("tool_call_count", 0) >= settings.max_tool_calls:
        reasons.append("Tool-call budget exhausted")
    started_at = state.get("started_at", time.time())
    if time.time() - started_at >= settings.max_duration_seconds:
        reasons.append("Investigation time budget exhausted")
    return reasons


def _fallback_report(state: AgentState, reasons: list[str]) -> DiagnosisReport:
    return DiagnosisReport(
        incident_id=state["incident"]["incident_id"],
        root_cause_status="insufficient_evidence",
        immediate_failure="The bounded investigation ended before a grounded cause was established.",
        probable_root_cause="Insufficient evidence",
        confidence=0.3,
        missing_information=reasons or ["Additional targeted operational evidence is required."],
        validation_status="rejected",
        escalation_reasons=reasons,
    )


def build_graph(
    settings: Settings,
    toolkit: ToolKit,
    model,
    checkpointer=None,
    audit: AuditLogger | None = None,
    jira_provider: JiraTicketProvider | None = None,
    orchestration_reporter: OrchestrationUIReporter | None = None,
):
    """Build the bounded supervisor, selective-ToT, evidence-gate, and HITL graph."""

    try:
        from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
        from langchain_core.tools import tool
        from langgraph.graph import END, START, MessagesState, StateGraph
        from langgraph.types import interrupt
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install live-agent support: pip install -e '.[agent]'") from exc

    instructions = load_agent_instructions(settings.agent_instructions_file)
    jira = jira_provider or DisabledJiraTicketProvider()

    class State(MessagesState, total=False):
        incident: dict
        evidence: list[dict]
        step_count: int
        tool_call_count: int
        retry_count: int
        started_at: float
        candidate_report: dict | None
        hypotheses: list[dict]
        branch_results: list[dict]
        critic: dict | None
        final_report: dict | None
        validation_errors: list[str]
        escalation_reasons: list[str]
        human_review: dict | None
        jira_ticket: dict | None
        memory_admission: dict | None

    def log_event(state: dict, event_type: str, **details) -> None:
        if audit:
            audit.record(event_type, state["incident"]["incident_id"], **details)

    @tool(description=instructions.tool_descriptions["list_logs"])
    def list_logs(application: str = "", limit: int = 50) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["inspect_log_summary"])
    def inspect_log_summary(path: str) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["search_logs"])
    def search_logs(path: str, query: str, max_matches: int = 20) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["get_log_context"])
    def get_log_context(path: str, line_number: int, before: int = 4, after: int = 6) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["query_metrics"])
    def query_metrics(metric_name: str) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["search_source_code"])
    def search_source_code(query: str, application: str = "", max_matches: int = 25) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["get_recent_changes"])
    def get_recent_changes(application: str) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["search_confluence_mcp"])
    def search_confluence_mcp(query: str) -> str:
        return ""

    @tool(description=instructions.tool_descriptions["search_validated_incidents"])
    def search_validated_incidents(query: str, application: str = "", top_k: int = 3) -> str:
        return ""

    tools = [
        list_logs,
        inspect_log_summary,
        search_logs,
        get_log_context,
        query_metrics,
        search_source_code,
        get_recent_changes,
        search_confluence_mcp,
        search_validated_incidents,
    ]
    bound_model = model.bind_tools(tools)

    def triage_node(state: dict) -> dict:
        started_at = state.get("started_at", time.time())
        evidence = list(state.get("evidence", []))
        tool_count = state.get("tool_call_count", 0)
        log_path = state["incident"].get("log_path")
        action = "inspect_log_summary" if log_path else "list_logs"
        args = {"path": log_path} if log_path else {
            "application": state["incident"].get("application"), "limit": 20
        }
        _console_phase(
            1,
            "Triage",
            "Locating the first operational signal for this incident.",
            action=action,
            target=log_path or state["incident"].get("application"),
        )
        try:
            result = toolkit.execute(action, args)
        except Exception as exc:
            result = ToolResult(
                source=EvidenceSource.LOG,
                category=EvidenceCategory.OPERATIONAL,
                summary="Triage could not read the requested local log",
                content=str(exc),
                metadata={"action": action},
                substantive=False,
            )
        item = _new_evidence(result, evidence)
        evidence.append(item.model_dump(mode="json"))
        _console_detail(
            "Initial evidence captured.",
            evidence_id=item.evidence_id,
            usable="yes" if item.substantive else "no",
            finding=item.summary,
        )
        log_event(state, "triage", action=action, evidence_id=item.evidence_id,
                  substantive=item.substantive)
        return {
            "evidence": evidence,
            "started_at": started_at,
            "tool_call_count": tool_count + 1,
            "messages": [
                SystemMessage(
                    content=instructions.render(
                        "triage_recorded_message",
                        evidence_id=item.evidence_id,
                        summary=item.summary,
                    )
                )
            ],
        }

    def supervisor_node(state: dict) -> dict:
        budget = _budget_reasons(state, settings)
        if budget:
            report = _fallback_report(state, budget)
            _console_phase(
                2,
                "Supervisor",
                "Safety budget reached; ending autonomous investigation.",
                reason=" | ".join(budget),
            )
            log_event(state, "budget_exhausted", reasons=budget)
            return {
                "messages": [AIMessage(content=report.model_dump_json())],
                "candidate_report": report.model_dump(mode="json"),
                "escalation_reasons": budget,
            }
        prompt = system_prompt(
            instructions,
            state["incident"],
            state.get("evidence", []),
            state.get("step_count", 0),
            settings.max_steps,
        )
        next_step = state.get("step_count", 0) + 1
        _console_phase(
            2,
            "Supervisor",
            "Reasoning over the evidence and selecting the next bounded action.",
            reasoning_step=f"{next_step} of {settings.max_steps}",
            evidence_items=len(state.get("evidence", [])),
            tool_calls=f"{state.get('tool_call_count', 0)} of {settings.max_tool_calls}",
        )
        _console_detail("Calling the configured reasoning model...")
        response = bound_model.invoke([SystemMessage(content=prompt), *state.get("messages", [])])
        requested_tools = [
            call.get("name") for call in getattr(response, "tool_calls", [])
        ]
        _console_detail(
            "Supervisor response received.",
            next_action=(", ".join(requested_tools) if requested_tools else "draft diagnosis report"),
        )
        log_event(state, "supervisor_reasoned", step=state.get("step_count", 0) + 1,
                  requested_tools=requested_tools)
        return {"messages": [response], "step_count": state.get("step_count", 0) + 1}

    def route_after_supervisor(state: dict) -> Literal["execute_tool", "draft"]:
        last = state["messages"][-1]
        return "execute_tool" if getattr(last, "tool_calls", None) else "draft"

    def execute_tool_node(state: dict) -> dict:
        calls = list(getattr(state["messages"][-1], "tool_calls", []) or [])
        if not calls:
            return {}
        call = calls[0]
        name = str(call.get("name", ""))
        args = dict(call.get("args") or {})
        if name in {"search_source_code", "search_validated_incidents"} and not args.get("application"):
            args["application"] = state["incident"].get("application") or None
        safe_args = ", ".join(f"{key}={_short(value, 80)}" for key, value in args.items())
        _console_phase(
            3,
            "Read-only tool",
            f"Executing {name} to gather grounded evidence.",
            arguments=safe_args,
        )
        try:
            if state.get("tool_call_count", 0) >= settings.max_tool_calls:
                raise RuntimeError("Tool-call budget exhausted")
            result = toolkit.execute(name, args)
        except Exception as exc:
            result = ToolResult(
                source=EvidenceSource.LOG,
                category=EvidenceCategory.OPERATIONAL,
                summary=f"Read-only tool {name!r} failed safely",
                content=str(exc),
                metadata={"tool_name": name},
                substantive=False,
            )
        _console_detail(
            "Tool completed safely.",
            source=result.source.value,
            category=result.category.value,
            usable="yes" if result.substantive else "no",
            result=result.summary,
        )
        log_event(state, "tool_call", tool=name, arguments=args, substantive=result.substantive)
        message = ToolMessage(
            content=result.model_dump_json(),
            tool_call_id=call.get("id", "missing-tool-call-id"),
            name=name,
        )
        return {
            "messages": [message],
            "tool_call_count": state.get("tool_call_count", 0) + 1,
        }

    def remember_node(state: dict) -> dict:
        last = state["messages"][-1]
        result = ToolResult.model_validate_json(_message_text(last))
        evidence = list(state.get("evidence", []))
        item = _new_evidence(result, evidence)
        evidence.append(item.model_dump(mode="json"))
        _console_phase(
            4,
            "Evidence ledger",
            "Normalizing the tool result and adding it to the auditable evidence set.",
            evidence_id=item.evidence_id,
            source=item.source.value,
            evidence_count=len(evidence),
            finding=item.summary,
        )
        log_event(state, "evidence_recorded", evidence_id=item.evidence_id,
                  source=item.source.value, category=item.category.value,
                  substantive=item.substantive)
        return {
            "evidence": evidence,
            "messages": [
                SystemMessage(
                    content=instructions.render(
                        "evidence_recorded_message",
                        evidence_id=item.evidence_id,
                        summary=item.summary,
                    )
                )
            ],
        }

    def draft_node(state: dict) -> dict:
        if state.get("candidate_report"):
            return {}
        try:
            report = DiagnosisReport.model_validate_json(_message_text(state["messages"][-1]))
            report.review_status = "pending"
            _console_phase(
                5,
                "Diagnostic draft",
                "The supervisor produced a schema-valid candidate diagnosis.",
                immediate_failure=report.immediate_failure,
                probable_cause=report.probable_root_cause,
                confidence=f"{report.confidence:.0%}",
                cited_evidence=", ".join(report.evidence_ids) or "none",
                alternatives=len(report.alternatives),
            )
            return {"candidate_report": report.model_dump(mode="json"), "retry_count": 0}
        except (ValidationError, ValueError) as exc:
            retries = state.get("retry_count", 0) + 1
            if retries > settings.max_retries:
                report = _fallback_report(state, ["Model repeatedly returned an invalid report schema"])
                _console_phase(
                    5,
                    "Diagnostic draft",
                    "Schema retries were exhausted; using a safe insufficient-evidence report.",
                    retries=retries,
                )
                return {
                    "candidate_report": report.model_dump(mode="json"),
                    "retry_count": retries,
                    "escalation_reasons": report.escalation_reasons,
                }
            log_event(state, "schema_validation_failed", retry=retries, error=str(exc))
            _console_phase(
                5,
                "Diagnostic draft",
                "The draft failed schema validation and will be regenerated.",
                retry=f"{retries} of {settings.max_retries}",
                validation_error=str(exc),
            )
            return {
                "messages": [
                    SystemMessage(content=instructions.schema_validation_failed_message)
                ],
                "retry_count": retries,
            }

    def route_after_draft(state: dict) -> Literal["supervisor", "hypothesize"]:
        return "hypothesize" if state.get("candidate_report") else "supervisor"

    def hypothesize_node(state: dict) -> dict:
        report = DiagnosisReport.model_validate(state["candidate_report"])
        evidence = state.get("evidence", [])
        prompt = instructions.render(
            "hypothesis_prompt",
            draft_json=report.model_dump_json(),
            evidence_json=json.dumps(evidence, default=str),
        )
        _console_phase(
            6,
            "Hypothesis generation",
            "Expanding the draft into independently reviewable root-cause theories.",
            maximum_branches=settings.max_branches,
        )
        try:
            structured = model.with_structured_output(HypothesisSet, method="json_schema")
            result = structured.invoke(prompt)
            hypotheses = result.hypotheses[: settings.max_branches]
        except Exception as exc:
            statements = [report.probable_root_cause, *report.alternatives]
            hypotheses = [
                Hypothesis(hypothesis_id=f"H{index}", statement=statement,
                           confidence=min(report.confidence, 0.95))
                for index, statement in enumerate(filter(None, statements[: settings.max_branches]), 1)
            ] or [Hypothesis(statement="Insufficient evidence", confidence=0.3)]
            log_event(state, "hypothesis_fallback", error=str(exc))
        for index, hypothesis in enumerate(hypotheses, 1):
            hypothesis.hypothesis_id = f"H{index}"
        multiple = len(hypotheses) > 1
        for hypothesis in hypotheses:
            _console_detail(
                f"{hypothesis.hypothesis_id}: {hypothesis.statement}",
                initial_confidence=f"{hypothesis.confidence:.0%}",
            )
        log_event(state, "hypotheses_generated", count=len(hypotheses), multiple=multiple)
        return {"hypotheses": [item.model_dump(mode="json") for item in hypotheses]}

    def branch_node(state: dict) -> dict:
        evidence = state.get("evidence", [])
        assessments: list[BranchAssessment] = []
        structured = model.with_structured_output(BranchAssessment, method="json_schema")
        _console_phase(
            7,
            "Branch evaluation",
            "Testing each theory against supporting, contradicting, and missing evidence.",
            branches=len(state.get("hypotheses", [])),
        )
        for raw in state.get("hypotheses", [])[: settings.max_branches]:
            hypothesis = Hypothesis.model_validate(raw)
            prompt = instructions.render(
                "branch_prompt",
                hypothesis_json=hypothesis.model_dump_json(),
                evidence_json=json.dumps(evidence, default=str),
            )
            _console_detail(f"Evaluating {hypothesis.hypothesis_id}: {hypothesis.statement}")
            try:
                assessment = structured.invoke(prompt)
                assessment.hypothesis_id = hypothesis.hypothesis_id
                assessment.depth = min(1, settings.max_branch_depth)
            except Exception as exc:
                assessment = BranchAssessment(
                    hypothesis_id=hypothesis.hypothesis_id,
                    depth=1,
                    score=hypothesis.confidence,
                    supporting_evidence_ids=hypothesis.supporting_evidence_ids,
                    contradicting_evidence_ids=hypothesis.contradicting_evidence_ids,
                    missing_information=["Branch model evaluation failed"],
                    conclusion=hypothesis.statement,
                )
                log_event(state, "branch_fallback", hypothesis_id=hypothesis.hypothesis_id,
                          error=str(exc))
            assessments.append(assessment)
            _console_detail(
                f"{assessment.hypothesis_id} evaluation complete.",
                score=f"{assessment.score:.0%}",
                supports=", ".join(assessment.supporting_evidence_ids) or "none",
                contradictions=", ".join(assessment.contradicting_evidence_ids) or "none",
                conclusion=assessment.conclusion,
            )
            log_event(state, "branch_scored", hypothesis_id=assessment.hypothesis_id,
                      score=assessment.score, depth=assessment.depth)
        return {"branch_results": [item.model_dump(mode="json") for item in assessments]}

    def critic_node(state: dict) -> dict:
        report = DiagnosisReport.model_validate(state["candidate_report"])
        branches = [BranchAssessment.model_validate(item) for item in state.get("branch_results", [])]
        if not branches:
            hypotheses = [Hypothesis.model_validate(item) for item in state.get("hypotheses", [])]
            branches = [
                BranchAssessment(
                    hypothesis_id=hypotheses[0].hypothesis_id,
                    score=hypotheses[0].confidence,
                    supporting_evidence_ids=hypotheses[0].supporting_evidence_ids,
                    contradicting_evidence_ids=hypotheses[0].contradicting_evidence_ids,
                    conclusion=hypotheses[0].statement,
                )
            ]
        prompt = instructions.render(
            "critic_prompt",
            branches_json=json.dumps(
                [item.model_dump(mode="json") for item in branches]
            ),
        )
        _console_phase(
            8,
            "Critic",
            "Comparing branch quality and selecting the best-supported theory.",
            candidates=len(branches),
        )
        try:
            critic = model.with_structured_output(CriticAssessment, method="json_schema").invoke(prompt)
        except Exception as exc:
            ordered = sorted(branches, key=lambda item: item.score, reverse=True)
            best = ordered[0]
            critic = CriticAssessment(
                selected_hypothesis_id=best.hypothesis_id,
                converged=len(ordered) == 1 or (best.score - ordered[1].score >= 0.15),
                evidence_score=best.score,
                contradiction_score=min(1.0, 0.25 * len(best.contradicting_evidence_ids)),
                unresolved_contradictions=best.contradicting_evidence_ids,
                feedback="Deterministic critic fallback used after structured-model failure.",
            )
            log_event(state, "critic_fallback", error=str(exc))
        selected = next(
            (item for item in state.get("hypotheses", [])
             if item.get("hypothesis_id") == critic.selected_hypothesis_id),
            None,
        )
        if selected:
            report.probable_root_cause = selected["statement"]
        selected_branch = next(
            (
                item
                for item in branches
                if item.hypothesis_id == critic.selected_hypothesis_id
            ),
            None,
        )
        if selected_branch and selected_branch.supporting_evidence_ids:
            report.evidence_ids = list(selected_branch.supporting_evidence_ids)
        report.confidence = min(report.confidence, critic.evidence_score, 0.95)
        escalation = list(state.get("escalation_reasons", []))
        if not critic.converged:
            escalation.append("Tree-of-Thought branches did not converge")
        if critic.unresolved_contradictions:
            escalation.append("Current evidence contains unresolved contradictions")
        _console_detail(
            "Critic assessment complete.",
            selected=critic.selected_hypothesis_id or "none",
            converged="yes" if critic.converged else "no",
            evidence_score=f"{critic.evidence_score:.0%}",
            contradiction_score=f"{critic.contradiction_score:.0%}",
            feedback=critic.feedback,
        )
        log_event(state, "critic_evaluated", converged=critic.converged,
                  evidence_score=critic.evidence_score,
                  contradiction_score=critic.contradiction_score)
        return {
            "critic": critic.model_dump(mode="json"),
            "candidate_report": report.model_dump(mode="json"),
            "escalation_reasons": list(dict.fromkeys(escalation)),
        }

    def evidence_gate_node(state: dict) -> dict:
        report = DiagnosisReport.model_validate(state["candidate_report"])
        evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
        result = validate_diagnosis(report, evidence)
        report.validation_status = result.validation_status
        escalation = list(state.get("escalation_reasons", []))
        if report.confidence < 0.65:
            escalation.append("Low diagnostic confidence")
        escalation.extend(result.reasons)
        budget = _budget_reasons(state, settings)
        escalation.extend(budget)
        if state["incident"].get("high_impact"):
            escalation.append("High-impact incident")
        if state["incident"].get("policy_sensitive"):
            escalation.append("Policy-sensitive incident")
        if state["incident"].get("production_change_requested"):
            escalation.append("Production change requested; autonomous execution is prohibited")
        report.escalation_reasons = list(dict.fromkeys(escalation))
        _console_phase(
            9,
            "Evidence and safety gate",
            (
                "PASS - the diagnosis is grounded enough to present for human review."
                if result.valid
                else "NEEDS REVIEW - automated validation found evidence gaps."
            ),
            validation_status=result.validation_status,
            confidence=f"{report.confidence:.0%}",
            cited_evidence=", ".join(report.evidence_ids) or "none",
            gate_findings=" | ".join(result.reasons) or "No blocking findings",
            escalations=" | ".join(report.escalation_reasons) or "none",
        )
        log_event(state, "evidence_gate", valid=result.valid, reasons=result.reasons)
        message = None
        if not result.valid:
            message = SystemMessage(
                content=instructions.render(
                    "evidence_gate_rejected_message",
                    reasons=" | ".join(result.reasons),
                )
            )
        update = {
            "candidate_report": report.model_dump(mode="json"),
            "validation_errors": result.reasons,
            "escalation_reasons": report.escalation_reasons,
            "retry_count": state.get("retry_count", 0) + (0 if result.valid else 1),
        }
        if message:
            update["messages"] = [message]
        return update

    def route_after_gate(state: dict) -> Literal["supervisor", "human_review"]:
        report = DiagnosisReport.model_validate(state["candidate_report"])
        if report.validation_status == "validated":
            return "human_review"
        if not _budget_reasons(state, settings) and state.get("retry_count", 0) < settings.max_retries:
            return "supervisor"
        return "human_review"

    def human_review_node(state: dict) -> dict:
        report = DiagnosisReport.model_validate(state["candidate_report"])
        if not settings.require_human_review:
            report.escalation_reasons.append("Human review is disabled; trusted-memory admission blocked")
            return {"final_report": report.model_dump(mode="json")}
        payload = {
            "type": "human_diagnostic_review",
            "incident_id": report.incident_id,
            "automated_validation": report.validation_status,
            "draft_report": report.model_dump(mode="json"),
            "critic": state.get("critic"),
            "escalation_reasons": state.get("escalation_reasons", []),
            "allowed_decisions": (
                ["confirm", "correct", "reject"]
                if report.validation_status == "validated" else ["correct", "reject"]
            ),
            "required_fields": {
                "confirm": ["reviewer", "actual_remediation"],
                "correct": ["reviewer", "corrected_root_cause", "actual_remediation"],
                "reject": ["reviewer"],
            },
        }
        payload["ui_review"] = build_ui_review_item(
            state, report.model_dump(mode="json")
        )
        review = HumanReview.model_validate(interrupt(payload))
        if review.decision.value == "confirm" and report.validation_status != "validated":
            raise ValueError("An evidence-gate-rejected draft cannot be confirmed; correct or reject it")
        if review.diagnosis_confidence is not None:
            report.confidence = review.diagnosis_confidence
        if review.evidence_ids:
            report.evidence_ids = list(review.evidence_ids)
        reviewed = apply_human_review(report, review)
        _console_detail(
            "Human decision returned to the durable LangGraph thread.",
            reviewer=review.reviewer,
            decision=review.decision.value,
            diagnosis=review.diagnosis_id or "critic-selected theory",
        )
        log_event(state, "human_review", decision=review.decision.value, reviewer=review.reviewer)
        return {
            "human_review": review.model_dump(mode="json"),
            "final_report": reviewed.model_dump(mode="json"),
        }

    def jira_ticket_node(state: dict) -> dict:
        report = DiagnosisReport.model_validate(
            state.get("final_report") or state["candidate_report"]
        )
        review_data = state.get("human_review")
        _console_phase(
            11,
            "Jira delivery",
            "Applying the deterministic post-review Jira policy.",
            review_status=report.review_status,
        )
        if report.review_status not in {"confirmed", "corrected"} or not review_data:
            result = JiraTicketResult(status="not_required")
        else:
            review = HumanReview.model_validate(review_data)
            critic = state.get("critic") or {}
            diagnosis_id = review.diagnosis_id or critic.get("selected_hypothesis_id")
            evidence_by_id = {
                str(item.get("evidence_id")): item
                for item in state.get("evidence", [])
            }
            report.evidence_details = [
                EvidenceDetail(
                    evidence_id=evidence_id,
                    source=str(item.get("source", "unknown")).replace("_", " ").title(),
                    summary=str(item.get("summary") or "Evidence collected"),
                    detail=str(item.get("content") or item.get("summary") or "")[:4000],
                )
                for evidence_id in report.evidence_ids
                if (item := evidence_by_id.get(evidence_id)) is not None
            ]
            result = jira.create_or_get_ticket(
                state["incident"], report, review, diagnosis_id
            )
        _console_detail(
            "Jira step complete.",
            status=result.status,
            diagnosis=result.diagnosis_id,
            issue=result.issue_key,
            url=result.issue_url,
            error=result.error,
        )
        log_event(
            state,
            "jira_ticket",
            status=result.status,
            diagnosis_id=result.diagnosis_id,
            issue_key=result.issue_key,
            error=result.error,
        )
        return {"jira_ticket": result.model_dump(mode="json")}

    def finalize_node(state: dict) -> dict:
        report = DiagnosisReport.model_validate(
            state.get("final_report") or state["candidate_report"]
        )
        if eligible_for_trusted_memory(report):
            evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
            cited = [item for item in evidence if item.evidence_id in report.evidence_ids]
            record = IncidentRecord(
                incident_id=report.incident_id,
                application=state["incident"].get("application", "unknown"),
                component=state["incident"].get("component"),
                error_family=state["incident"].get("error_family"),
                symptoms=state["incident"].get("description", report.immediate_failure),
                validated_diagnosis=report.probable_root_cause,
                evidence_summary="; ".join(item.summary for item in cited),
                resolution=report.actual_remediation,
                review_status=report.review_status,
                reviewed_by=report.reviewer or "unknown",
                metadata={
                    "admitted_by": "review_gate",
                    "jira_ticket": state.get("jira_ticket"),
                    "jira_issue_key": (state.get("jira_ticket") or {}).get("issue_key"),
                    "jira_issue_url": (state.get("jira_ticket") or {}).get("issue_url"),
                },
            )
            try:
                toolkit.rag.add(record)
            except Exception as exc:
                error = _short(exc, 1000)
                _console_phase(
                    12,
                    "Finalize with warning",
                    "The reviewed result is complete, but trusted-memory persistence failed.",
                    review_status=report.review_status,
                    memory_status="failed - safe to retry",
                    error=error,
                )
                log_event(state, "trusted_memory_failed", error=error)
                return {
                    "final_report": report.model_dump(mode="json"),
                    "memory_admission": {"status": "failed", "error": error},
                }
            _console_phase(
                12,
                "Finalize and learn",
                "The reviewed outcome passed the trust gate and was admitted to incident memory.",
                review_status=report.review_status,
                reviewer=report.reviewer,
                root_cause=report.probable_root_cause,
            )
            log_event(state, "trusted_memory_admitted", review_status=report.review_status)
            return {
                "final_report": report.model_dump(mode="json"),
                "memory_admission": {"status": "admitted", "error": None},
            }
        else:
            _console_phase(
                12,
                "Finalize safely",
                "The run completed, but this outcome was not eligible for trusted memory.",
                validation_status=report.validation_status,
                review_status=report.review_status,
            )
            log_event(state, "trusted_memory_blocked", validation=report.validation_status,
                      review=report.review_status)
        return {
            "final_report": report.model_dump(mode="json"),
            "memory_admission": {"status": "blocked", "error": None},
        }

    def tracked_node(name: str, node):
        if orchestration_reporter is None:
            return node

        def run(state: dict) -> dict:
            orchestration_reporter.node_started(name, state)
            try:
                updates = node(state)
            except Exception as exc:
                if "GraphInterrupt" in type(exc).__name__:
                    orchestration_reporter.node_waiting(name, state)
                else:
                    orchestration_reporter.node_failed(name, state, exc)
                raise
            orchestration_reporter.node_completed(name, state, updates)
            return updates

        return run

    graph = StateGraph(State)
    graph.add_node("triage", tracked_node("triage", triage_node))
    graph.add_node("supervisor", tracked_node("supervisor", supervisor_node))
    graph.add_node("execute_tool", tracked_node("execute_tool", execute_tool_node))
    graph.add_node("remember", tracked_node("remember", remember_node))
    graph.add_node("draft", tracked_node("draft", draft_node))
    graph.add_node("hypothesize", tracked_node("hypothesize", hypothesize_node))
    graph.add_node("branches", tracked_node("branches", branch_node))
    graph.add_node("critic", tracked_node("critic", critic_node))
    graph.add_node("evidence_gate", tracked_node("evidence_gate", evidence_gate_node))
    graph.add_node("human_review", tracked_node("human_review", human_review_node))
    graph.add_node("jira_ticket", tracked_node("jira_ticket", jira_ticket_node))
    graph.add_node("finalize", tracked_node("finalize", finalize_node))
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "supervisor")
    graph.add_conditional_edges("supervisor", route_after_supervisor)
    graph.add_edge("execute_tool", "remember")
    graph.add_edge("remember", "supervisor")
    graph.add_conditional_edges("draft", route_after_draft)
    graph.add_edge("hypothesize", "branches")
    graph.add_edge("branches", "critic")
    graph.add_edge("critic", "evidence_gate")
    graph.add_conditional_edges("evidence_gate", route_after_gate)
    graph.add_edge("human_review", "jira_ticket")
    graph.add_edge("jira_ticket", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def _prompt_for_review(payload: dict) -> HumanReview:
    print("\nHUMAN REVIEW REQUIRED")
    print(json.dumps(payload, indent=2, default=str))
    allowed = set(payload["allowed_decisions"])
    while True:
        decision = input(f"Decision ({'/'.join(sorted(allowed))}): ").strip().lower()
        if decision in allowed:
            break
        print("Choose one of:", ", ".join(sorted(allowed)))
    reviewer = input("Reviewer name: ").strip()
    corrected = input("Corrected root cause: ").strip() if decision == "correct" else None
    remediation = (
        input("Actual remediation outcome: ").strip()
        if decision in {"confirm", "correct"} else None
    )
    notes = input("Review notes (optional): ").strip() or None
    return HumanReview(
        decision=decision,
        reviewer=reviewer,
        corrected_root_cause=corrected,
        actual_remediation=remediation,
        notes=notes,
    )


def _run_graph(
    graph,
    initial: dict,
    config: dict,
    non_interactive: bool,
    *,
    review_ui_url: str,
    review_ui_poll_seconds: float,
    terminal_review: bool = False,
) -> dict:
    from langgraph.types import Command

    result = graph.invoke(initial, config=config)
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return result
    payload = interrupts[0].value
    if non_interactive:
        _console_phase(
            10,
            "Human review",
            "The graph is checkpointed and awaiting an external reviewer.",
            incident=payload.get("incident_id"),
            diagnoses=len(payload.get("ui_review", {}).get("payload", {}).get("diagnoses", [])),
        )
        print(json.dumps({"status": "awaiting_human_review", "review": payload}, indent=2))
        return result
    _console_phase(
        10,
        "Human review",
        (
            "Pausing the graph and handing the evidence package to SignalDesk."
            if not terminal_review
            else "Pausing the graph for review in this terminal."
        ),
        incident=payload.get("incident_id"),
        diagnoses=len(payload.get("ui_review", {}).get("payload", {}).get("diagnoses", [])),
        checkpoint="saved - safe to stop and resume",
    )
    if terminal_review:
        review = _prompt_for_review(payload)
    else:
        try:
            review = collect_review_in_ui(
                payload,
                review_ui_url,
                poll_seconds=review_ui_poll_seconds,
            )
        except ReviewUIError as exc:
            raise SystemExit(str(exc)) from exc
    _console_detail(
        "Resuming orchestration with the recorded human decision.",
        reviewer=review.reviewer,
        decision=review.decision.value,
        diagnosis=review.diagnosis_id,
    )
    result = graph.invoke(Command(resume=review.model_dump(mode="json")), config=config)
    ticket = result.get("jira_ticket")
    incident_id = payload.get("incident_id")
    if ticket and incident_id and ticket.get("status") != "not_required":
        try:
            publish_jira_result(review_ui_url, str(incident_id), ticket)
            _console_detail(
                "SignalDesk received the Jira delivery result.",
                issue=ticket.get("issue_key"),
                status=ticket.get("status"),
            )
        except ReviewUIError as exc:
            _console_detail(
                "Jira delivery succeeded, but SignalDesk could not be updated.",
                error=exc,
            )
    return result


def main() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional convenience
        load_dotenv = None

    parser = argparse.ArgumentParser(description="Run the safety-bounded LangGraph diagnostic agent")
    parser.add_argument("--log", default=None, help="Path relative to C:\\AI_Repo\\logs")
    parser.add_argument("--incident-id", default="LOCAL-INCIDENT-001")
    parser.add_argument("--application", default="PropertyCasualtyInsuranceAgentInfo")
    parser.add_argument(
        "--description",
        default=None,
        help="Incident request; defaults to default_incident_description in the instructions file",
    )
    parser.add_argument("--thread-id", default=None)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument(
        "--terminal-review",
        action="store_true",
        help="Use the legacy PowerShell review prompt instead of SignalDesk",
    )
    parser.add_argument(
        "--review-ui-url",
        default=None,
        help="SignalDesk base URL; defaults to SIGNALDESK_UI_URL",
    )
    parser.add_argument("--high-impact", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    if load_dotenv:
        load_dotenv(project_root / ".env")
    settings = Settings.from_env(project_root)
    instructions = load_agent_instructions(settings.agent_instructions_file)
    incident_description = args.description or instructions.default_incident_description
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for the live Codex agent")
    if settings.use_pgvector and not settings.database_url:
        raise SystemExit("DATABASE_URL is required when USE_PGVECTOR=true")
    try:
        checkpoint_connection_url(
            settings.database_url,
            settings.checkpoint_database_url,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    toolkit = ToolKit.from_settings(settings)
    setup = getattr(toolkit.rag, "setup", None)
    if setup:
        setup()
    audit = AuditLogger(settings.audit_log)
    from .tools.jira import jira_provider_from_settings

    jira_provider = jira_provider_from_settings(settings)

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Install live dependencies: pip install -e '.[agent,postgres]'") from exc

    model = ChatOpenAI(
        model=settings.llm_model,
        use_responses_api=True,
        reasoning={"effort": settings.reasoning_effort, "summary": "auto"},
        store=False,
        max_retries=settings.max_retries,
    )
    initial = {
        "messages": [{"role": "user", "content": incident_description}],
        "incident": {
            "incident_id": args.incident_id,
            "application": args.application,
            "log_path": args.log,
            "description": incident_description,
            "high_impact": args.high_impact,
        },
        "evidence": [],
        "step_count": 0,
        "tool_call_count": 0,
        "retry_count": 0,
        "started_at": time.time(),
        "candidate_report": None,
        "hypotheses": [],
        "branch_results": [],
        "critic": None,
        "final_report": None,
        "validation_errors": [],
        "escalation_reasons": [],
        "human_review": None,
        "jira_ticket": None,
        "memory_admission": None,
    }
    thread_id = args.thread_id or args.incident_id
    config = {"configurable": {"thread_id": thread_id}}
    _console_banner(initial["incident"], settings, thread_id)
    orchestration_reporter = None
    if settings.orchestration_ui_enabled:
        orchestration_reporter = OrchestrationUIReporter(
            args.review_ui_url or settings.review_ui_url,
            f"{thread_id}-{uuid4().hex[:8]}",
            initial["incident"],
            delay_seconds=settings.orchestration_demo_delay_seconds,
        )
    _console_detail(
        "Initializing durable checkpoint storage and read-only diagnostic tools.",
        checkpoint_store="PostgreSQL/Supabase" if settings.checkpoint_database_url else "configured database",
        log_source=args.log or "automatic application log discovery",
    )
    with open_checkpointer(
        database_url=settings.database_url,
        checkpoint_database_url=settings.checkpoint_database_url,
    ) as checkpointer:
        graph = build_graph(
            settings,
            toolkit,
            model,
            checkpointer=checkpointer,
            audit=audit,
            jira_provider=jira_provider,
            orchestration_reporter=orchestration_reporter,
        )
        if orchestration_reporter:
            orchestration_reporter.start(initial)
        result = _run_graph(
            graph,
            initial,
            config,
            args.non_interactive,
            review_ui_url=args.review_ui_url or settings.review_ui_url,
            review_ui_poll_seconds=settings.review_ui_poll_seconds,
            terminal_review=args.terminal_review,
        )
    if orchestration_reporter and result.get("final_report"):
        orchestration_reporter.complete(result)
    if result.get("final_report"):
        report = DiagnosisReport.model_validate(result["final_report"])
        print("\n" + "=" * CONSOLE_WIDTH, flush=True)
        print(" ORCHESTRATION COMPLETE", flush=True)
        print("=" * CONSOLE_WIDTH, flush=True)
        print(f" Result       : {report.review_status}", flush=True)
        print(f" Root cause   : {_short(report.probable_root_cause, 240)}", flush=True)
        print(f" Confidence   : {report.confidence:.0%}", flush=True)
        print(f" Reviewer     : {report.reviewer or 'not reviewed'}", flush=True)
        if result.get("jira_ticket"):
            ticket = JiraTicketResult.model_validate(result["jira_ticket"])
            print(
                f" Jira         : {ticket.issue_key or ticket.status}"
                + (f" ({ticket.issue_url})" if ticket.issue_url else ""),
                flush=True,
            )
        if result.get("memory_admission"):
            print(
                f" Memory       : {result['memory_admission'].get('status')}",
                flush=True,
            )
        print("=" * CONSOLE_WIDTH, flush=True)
        print("\nFINAL STRUCTURED REPORT", flush=True)
        print(json.dumps(result["final_report"], indent=2, default=str))
    if result.get("jira_ticket"):
        print("\nJIRA DELIVERY RESULT", flush=True)
        print(json.dumps({"jira_ticket": result["jira_ticket"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
