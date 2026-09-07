from __future__ import annotations

import json
import os
import time
import webbrowser
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote, urljoin
from uuid import uuid4

from .ui_review import ReviewUIError, _request_json


NODE_MESSAGES = {
    "triage": "Framing the incident and locating the first operational signal",
    "supervisor": "Selecting the next bounded action from the current evidence",
    "execute_tool": "Running one allowlisted, read-only evidence tool",
    "remember": "Normalizing the observation into the evidence ledger",
    "draft": "Building a typed diagnostic report from grounded findings",
    "hypothesize": "Forming alternative explanations for independent evaluation",
    "branches": "Testing candidate diagnoses against supporting and conflicting evidence",
    "critic": "Comparing branch strength and unresolved contradictions",
    "evidence_gate": "Applying deterministic evidence and citation checks",
    "human_review": "Waiting for an accountable reviewer decision",
    "jira_ticket": "Delivering the approved diagnosis to Jira idempotently",
    "finalize": "Finalizing the report and trusted-memory decision",
}


def _clip(value: object, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _tool_call(state: dict) -> tuple[str | None, dict]:
    messages = state.get("messages") or []
    if not messages:
        return None, {}
    last = messages[-1]
    calls = getattr(last, "tool_calls", None)
    if calls is None and isinstance(last, dict):
        calls = last.get("tool_calls")
    if not calls:
        return None, {}
    call = calls[0]
    return str(call.get("name") or "read-only tool"), dict(call.get("args") or {})


def _activity(node: str | None, state: dict, updates: dict | None, event_type: str) -> dict:
    merged = {**state, **(updates or {})}
    incident = merged.get("incident") or {}
    report = merged.get("final_report") or merged.get("candidate_report") or {}
    evidence = merged.get("evidence") or []
    facts: list[dict[str, str]] = []
    title = NODE_MESSAGES.get(node or "", "Agent orchestration update")
    body = _clip(incident.get("description") or f"Processing {incident.get('incident_id', 'incident')}.")

    if node == "triage":
        if event_type == "node_completed" and evidence:
            item = evidence[-1]
            title = f"Captured {item.get('evidence_id', 'new evidence')}"
            body = _clip(item.get("summary") or item.get("content"))
            facts = [
                {"label": "Source", "value": str(item.get("source") or "operational data")},
                {"label": "Usable", "value": "Yes" if item.get("substantive") else "Limited"},
            ]
        else:
            title = f"Starting {incident.get('incident_id', 'incident')}"
            facts = [
                {"label": "Application", "value": _clip(incident.get("application"), 80)},
                {"label": "Target", "value": _clip(incident.get("log_path") or "automatic log discovery", 90)},
            ]
    elif node == "supervisor":
        tool_name, arguments = _tool_call({**state, **(updates or {})})
        if event_type == "node_completed" and tool_name:
            title = f"Next action: {tool_name.replace('_', ' ')}"
            body = "The supervisor selected one allowlisted observation based on the evidence collected so far."
            if arguments:
                facts.append({"label": "Input", "value": _clip(json.dumps(arguments, default=str), 110)})
        elif event_type == "node_completed":
            title = "Evidence collection is sufficient"
            body = "The supervisor is moving from investigation into a structured diagnostic draft."
        else:
            title = f"Reviewing {len(evidence)} evidence item{'s' if len(evidence) != 1 else ''}"
            body = "The model is choosing whether to gather another signal or draft the diagnosis."
        facts.append({"label": "Reasoning step", "value": str(merged.get("step_count", 0))})
    elif node == "execute_tool":
        tool_name, arguments = _tool_call(state)
        result_message = ((updates or {}).get("messages") or [None])[-1]
        if event_type == "node_completed" and result_message is not None:
            raw_content = getattr(result_message, "content", "")
            try:
                result = json.loads(str(raw_content))
            except (TypeError, ValueError, json.JSONDecodeError):
                result = {}
            title = f"{getattr(result_message, 'name', None) or tool_name or 'Tool'} returned"
            body = _clip(result.get("summary") or raw_content)
            facts = [
                {"label": "Source", "value": str(result.get("source") or "read-only tool")},
                {"label": "Usable", "value": "Yes" if result.get("substantive") else "Limited"},
            ]
        else:
            title = f"Running {(tool_name or 'read-only tool').replace('_', ' ')}"
            body = "The action is constrained by configured paths, byte limits, and secret redaction."
            if arguments:
                facts = [{"label": "Input", "value": _clip(json.dumps(arguments, default=str), 110)}]
    elif node == "remember" and evidence:
        item = evidence[-1]
        title = f"{item.get('evidence_id', 'Evidence')} added to the ledger"
        body = _clip(item.get("summary") or item.get("content"))
        facts = [
            {"label": "Source", "value": str(item.get("source") or "unknown")},
            {"label": "Total evidence", "value": str(len(evidence))},
        ]
    elif node == "draft":
        title = _clip(report.get("probable_root_cause") or "Structuring the diagnostic report", 110)
        body = _clip(report.get("immediate_failure") or "Separating observed facts, inferences, unknowns, and actions.")
        facts = [
            {"label": "Confidence", "value": f"{float(report.get('confidence', 0)):.0%}" if report else "Pending"},
            {"label": "Citations", "value": ", ".join(report.get("evidence_ids") or []) or "Being resolved"},
        ]
    elif node == "hypothesize":
        hypotheses = merged.get("hypotheses") or []
        title = f"Generated {len(hypotheses)} competing hypothes{'es' if len(hypotheses) != 1 else 'is'}" if hypotheses else "Generating competing hypotheses"
        body = _clip(" • ".join(f"{item.get('hypothesis_id')}: {item.get('statement')}" for item in hypotheses) or report.get("probable_root_cause"))
        facts = [{"label": "Branch limit", "value": "3"}]
    elif node == "branches":
        branches = merged.get("branch_results") or []
        leading = max(branches, key=lambda item: float(item.get("score", 0)), default={})
        title = f"Evaluated {len(branches)} diagnostic branch{'es' if len(branches) != 1 else ''}" if branches else "Evaluating diagnostic branches"
        body = _clip(leading.get("conclusion") or "Each theory is being checked for support, contradictions, and missing information.")
        if leading:
            facts = [
                {"label": "Leading", "value": str(leading.get("hypothesis_id") or "Unknown")},
                {"label": "Score", "value": f"{float(leading.get('score', 0)):.0%}"},
            ]
    elif node == "critic":
        critic = merged.get("critic") or {}
        title = f"Critic selected {critic.get('selected_hypothesis_id')}" if critic.get("selected_hypothesis_id") else "Critic comparing branch quality"
        body = _clip(critic.get("feedback") or "The critic is looking for weak support and unresolved disagreement.")
        if critic:
            facts = [
                {"label": "Converged", "value": "Yes" if critic.get("converged") else "No"},
                {"label": "Evidence score", "value": f"{float(critic.get('evidence_score', 0)):.0%}"},
            ]
    elif node == "evidence_gate":
        validation = report.get("validation_status")
        reasons = merged.get("validation_errors") or []
        title = "Evidence gate passed" if validation == "validated" else "Checking evidence requirements"
        body = _clip(" | ".join(reasons) or "Citations, operational source diversity, and contradictions are being checked deterministically.")
        facts = [
            {"label": "Validation", "value": str(validation or "In progress")},
            {"label": "Evidence cited", "value": ", ".join(report.get("evidence_ids") or []) or "None yet"},
        ]
    elif node == "human_review":
        review = merged.get("human_review") or {}
        if review:
            title = f"Decision received: {str(review.get('decision', '')).title()}"
            body = _clip(review.get("notes") or review.get("actual_remediation") or "The reviewer decision resumed the checkpoint.")
            facts = [
                {"label": "Reviewer", "value": _clip(review.get("reviewer"), 80)},
                {"label": "Diagnosis", "value": str(review.get("diagnosis_id") or "critic-selected")},
            ]
        else:
            title = "Waiting for an accountable decision"
            body = _clip(report.get("probable_root_cause") or "The checkpoint is saved until the review is submitted.")
            facts = [{"label": "Validation", "value": str(report.get("validation_status") or "pending")}]
    elif node == "jira_ticket":
        ticket = merged.get("jira_ticket") or {}
        if ticket:
            title = f"Jira {ticket.get('status')}: {ticket.get('issue_key') or ticket.get('diagnosis_id') or 'delivery result'}"
            body = _clip(ticket.get("error") or ticket.get("issue_url") or "The terminal Jira result has been recorded.")
            facts = [
                {"label": "Status", "value": str(ticket.get("status") or "unknown")},
                {"label": "Issue", "value": str(ticket.get("issue_key") or "Not created")},
            ]
        else:
            title = "Checking Jira before ticket creation"
            body = _clip(report.get("probable_root_cause") or "Searching by the stable incident and diagnosis label to prevent duplicates.")
            facts = [{"label": "Review", "value": str(report.get("review_status") or "pending")}]
    elif node == "finalize":
        memory = merged.get("memory_admission") or {}
        title = f"Trusted memory: {memory.get('status')}" if memory else "Finalizing the reviewed outcome"
        body = _clip(report.get("probable_root_cause") or "Recording the final report and memory-admission decision.")
        facts = [
            {"label": "Review", "value": str(report.get("review_status") or "pending")},
            {"label": "Jira", "value": str((merged.get("jira_ticket") or {}).get("issue_key") or "No issue")},
        ]

    return {"activityTitle": title, "activityBody": body, "activityFacts": facts[:3]}


class OrchestrationUIReporter:
    """Best-effort live telemetry for the separate orchestration demo UI."""

    def __init__(
        self,
        base_url: str,
        run_id: str,
        incident: dict,
        *,
        delay_seconds: float = 1.0,
        browser_open: Callable[[str], object] = webbrowser.open,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_url = urljoin(self.base_url, "api/orchestration")
        self.run_id = run_id
        self.incident_id = str(incident.get("incident_id") or run_id)
        self.application = str(incident.get("application") or "Unknown application")
        self.delay_seconds = max(0.0, delay_seconds)
        self.browser_open = browser_open
        self.sleep = sleep
        self.sequence = 0
        self._warned = False

    def _snapshot(
        self,
        state: dict,
        updates: dict | None = None,
        *,
        node: str | None = None,
        event_type: str = "run_started",
    ) -> dict:
        merged = {**state, **(updates or {})}
        report = merged.get("final_report") or merged.get("candidate_report") or {}
        confidence = report.get("confidence")
        if confidence is None:
            scores = [
                item.get("score", item.get("confidence"))
                for item in merged.get("branch_results", []) or merged.get("hypotheses", [])
            ]
            confidence = max((float(value) for value in scores if value is not None), default=None)
        ticket = merged.get("jira_ticket") or {}
        return {
            "evidenceCount": len(merged.get("evidence", [])),
            "confidence": confidence,
            "stepCount": int(merged.get("step_count", 0)),
            "toolCallCount": int(merged.get("tool_call_count", 0)),
            "jiraStatus": ticket.get("status"),
            "issueKey": ticket.get("issue_key"),
            "issueUrl": ticket.get("issue_url"),
            **_activity(node, state, updates, event_type),
        }

    def _publish(
        self,
        *,
        event_type: str,
        status: str,
        node: str | None,
        message: str,
        state: dict,
        updates: dict | None = None,
        error: str | None = None,
    ) -> None:
        self.sequence += 1
        now = datetime.now(timezone.utc).isoformat()
        body = {
            "eventId": str(uuid4()),
            "runId": self.run_id,
            "incidentId": self.incident_id,
            "application": self.application,
            "eventType": event_type,
            "sequence": self.sequence,
            "node": node,
            "status": status,
            "message": message,
            "details": self._snapshot(
                state,
                updates,
                node=node,
                event_type=event_type,
            ),
            "error": error,
            "createdAt": now,
        }
        try:
            _request_json(
                self.api_url,
                method="POST",
                body=body,
                bearer_token=os.getenv("SIGNALDESK_REVIEW_API_TOKEN") or None,
                timeout=2.0,
            )
        except ReviewUIError as exc:
            if not self._warned:
                print(f"  > Live orchestration UI unavailable: {exc}", flush=True)
                self._warned = True

    def start(self, state: dict) -> None:
        self._publish(
            event_type="run_started",
            status="running",
            node=None,
            message="Orchestration started",
            state=state,
        )
        run_url = f"{self.base_url}orchestration?runId={quote(self.run_id, safe='')}"
        self.browser_open(run_url)
        print("  > Live orchestration view opened in the default browser.", flush=True)
        print(f"    Orchestration URL: {run_url}", flush=True)

    def node_started(self, node: str, state: dict) -> None:
        self._publish(
            event_type="node_started",
            status="running",
            node=node,
            message=NODE_MESSAGES.get(node, f"Running {node}"),
            state=state,
        )

    def node_completed(self, node: str, state: dict, updates: dict) -> None:
        self._publish(
            event_type="node_completed",
            status="running",
            node=node,
            message=f"{NODE_MESSAGES.get(node, node.capitalize())} — complete",
            state=state,
            updates=updates,
        )
        if self.delay_seconds:
            self.sleep(self.delay_seconds)

    def node_waiting(self, node: str, state: dict) -> None:
        self._publish(
            event_type="node_waiting",
            status="waiting",
            node=node,
            message="Checkpoint saved; waiting for a reviewer decision",
            state=state,
        )

    def node_failed(self, node: str, state: dict, error: Exception) -> None:
        self._publish(
            event_type="node_failed",
            status="failed",
            node=node,
            message=f"{node.replace('_', ' ').title()} failed",
            state=state,
            error=str(error),
        )

    def complete(self, state: dict) -> None:
        self._publish(
            event_type="run_completed",
            status="completed",
            node="finalize",
            message="Orchestration complete",
            state=state,
        )
