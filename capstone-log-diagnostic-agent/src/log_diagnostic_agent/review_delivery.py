from __future__ import annotations

from typing import TypedDict

from .models import DiagnosisReport, EvidenceDetail, HumanReview, IncidentRecord
from .stores.base import IncidentRAGStore
from .tools.jira import JiraTicketProvider


class ReviewDeliveryState(TypedDict, total=False):
    incident: dict
    payload: dict
    decisions: list[dict]
    jira_tickets: list[dict]
    memory_admission: dict


def build_review_delivery_graph(
    jira_provider: JiraTicketProvider,
    rag_store: IncidentRAGStore | None = None,
):
    """Build the UI-review-to-Jira graph; no Jira write is exposed to an LLM."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install live-agent support: pip install -e '.[agent]'") from exc

    def jira_ticket_node(state: ReviewDeliveryState) -> dict:
        incident = state["incident"]
        payload = state["payload"]
        diagnoses = {item["id"]: item for item in payload.get("diagnoses", [])}
        changes = payload.get("suggestedChanges", [])
        results = []
        print("\n" + "-" * 88, flush=True)
        print("[LANGGRAPH DELIVERY] Processing SignalDesk reviewer decisions", flush=True)
        print(f"  Incident : {incident.get('incidentId')}", flush=True)
        print(f"  Decisions: {len(state.get('decisions', []))}", flush=True)
        for decision in state.get("decisions", []):
            if decision.get("decision") != "approved":
                print(
                    f"  - {decision.get('diagnosisId')}: {decision.get('decision')} "
                    "-> no Jira ticket required",
                    flush=True,
                )
                continue
            diagnosis_id = str(decision.get("diagnosisId", ""))
            diagnosis = diagnoses.get(diagnosis_id)
            if not diagnosis:
                print(f"  - {diagnosis_id}: skipped; diagnosis payload was not found", flush=True)
                continue
            print(
                f"  - {diagnosis_id}: approved by {decision.get('reviewerName')} "
                "-> creating or locating Jira ticket",
                flush=True,
            )
            related_changes = [
                item for item in changes
                if not item.get("diagnosisId") or item.get("diagnosisId") == diagnosis_id
            ]
            recommended_actions = []
            for item in related_changes:
                detail = [item.get("title"), item.get("detail"), item.get("implementation")]
                if item.get("files"):
                    detail.append("Files: " + ", ".join(item["files"]))
                if item.get("code"):
                    detail.append(
                        f"Suggested code ({item.get('language', 'text')}):\n{item['code']}"
                    )
                recommended_actions.append("\n".join(filter(None, detail)))
            evidence_by_id = {
                str(item.get("id")): item for item in payload.get("evidence", [])
            }
            evidence_ids = list(diagnosis.get("evidenceIds", []))
            report = DiagnosisReport(
                incident_id=incident["incidentId"],
                root_cause_status="probable",
                immediate_failure=incident.get("symptom") or incident.get("title", "Incident"),
                probable_root_cause=(
                    f"{diagnosis.get('title', diagnosis_id)}: {diagnosis.get('summary', '')}"
                ),
                confidence=float(diagnosis.get("confidence", 0)),
                evidence_ids=evidence_ids,
                evidence_details=[
                    EvidenceDetail(
                        evidence_id=evidence_id,
                        source=str(item.get("source") or "Unknown"),
                        summary=str(item.get("summary") or "Evidence collected"),
                        detail=str(item.get("detail") or item.get("summary") or "")[:4000],
                    )
                    for evidence_id in evidence_ids
                    if (item := evidence_by_id.get(evidence_id)) is not None
                ],
                recommended_actions=recommended_actions,
                validation_status="validated",
                review_status="confirmed",
                reviewer=decision.get("reviewerName"),
            )
            review = HumanReview(
                decision="confirm",
                reviewer=decision.get("reviewerName") or "Unknown reviewer",
                actual_remediation="Implementation is pending after reviewer approval.",
                notes=decision.get("comments"),
            )
            ticket = jira_provider.create_or_get_ticket(
                incident, report, review, diagnosis_id
            )
            print(
                f"    Jira result: {ticket.status}"
                + (f" | {ticket.issue_key}" if ticket.issue_key else "")
                + (f" | {ticket.error}" if ticket.error else ""),
                flush=True,
            )
            results.append(ticket.model_dump(mode="json"))
        print("[LANGGRAPH DELIVERY] Decision delivery complete", flush=True)
        return {"jira_tickets": results}

    def trusted_memory_node(state: ReviewDeliveryState) -> dict:
        successful = [
            ticket for ticket in state.get("jira_tickets", [])
            if ticket.get("status") in {"created", "existing"} and ticket.get("issue_url")
        ]
        if not successful:
            print("[TRUSTED MEMORY] No successful Jira ticket to persist", flush=True)
            return {"memory_admission": {"status": "not_required", "error": None}}
        if rag_store is None:
            print("[TRUSTED MEMORY] Incident-memory store is not configured", flush=True)
            return {"memory_admission": {"status": "not_configured", "error": None}}

        incident = state["incident"]
        payload = state["payload"]
        diagnoses = {item["id"]: item for item in payload.get("diagnoses", [])}
        approved = {
            str(item.get("diagnosisId")): item
            for item in state.get("decisions", [])
            if item.get("decision") == "approved"
        }
        successful_ids = [str(ticket.get("diagnosis_id")) for ticket in successful]
        selected = [diagnoses[item_id] for item_id in successful_ids if item_id in diagnoses]
        related_changes = [
            change for change in payload.get("suggestedChanges", [])
            if not change.get("diagnosisId") or change.get("diagnosisId") in successful_ids
        ]
        reviewers = sorted({
            str(approved[item_id].get("reviewerName") or "Unknown reviewer")
            for item_id in successful_ids if item_id in approved
        })
        diagnosis_summary = "; ".join(
            f"{item.get('title', item.get('id'))}: {item.get('summary', '')}" for item in selected
        )
        evidence_summary = "; ".join(
            f"{item.get('id')}: {item.get('detail', '')}"
            for item in payload.get("evidence", [])
        ) or "; ".join(
            f"{item_id}: {approved[item_id].get('comments', '')}"
            for item_id in successful_ids if item_id in approved
        )
        resolution = "; ".join(
            " - ".join(filter(None, [change.get("title"), change.get("detail"), change.get("implementation")]))
            for change in related_changes
        ) or "Implementation pending for the approved diagnosis."
        record = IncidentRecord(
            incident_id=incident["incidentId"],
            application=incident.get("application", "unknown"),
            component=payload.get("service"),
            symptoms=incident.get("symptom") or incident.get("title", "Incident"),
            validated_diagnosis=diagnosis_summary or "Approved diagnosis",
            evidence_summary=evidence_summary or "Approved by reviewer",
            resolution=resolution,
            review_status="confirmed",
            reviewed_by=", ".join(reviewers) or "Unknown reviewer",
            metadata={
                "admitted_by": "review_gate",
                "diagnosis_ids": successful_ids,
                "jira_issue_keys": [ticket.get("issue_key") for ticket in successful],
                "jira_issue_urls": [ticket.get("issue_url") for ticket in successful],
                "jira_tickets": successful,
            },
        )
        try:
            rag_store.add(record)
        except Exception as exc:
            error = str(exc)[:1000]
            print(f"[TRUSTED MEMORY] Persistence failed: {error}", flush=True)
            return {"memory_admission": {"status": "failed", "error": error}}
        print(
            f"[TRUSTED MEMORY] Saved {record.incident_id} with "
            f"{len(successful)} Jira link(s)",
            flush=True,
        )
        return {
            "memory_admission": {
                "status": "admitted",
                "jira_issue_urls": record.metadata["jira_issue_urls"],
                "error": None,
            }
        }

    graph = StateGraph(ReviewDeliveryState)
    graph.add_node("jira_ticket", jira_ticket_node)
    graph.add_node("trusted_memory", trusted_memory_node)
    graph.add_edge(START, "jira_ticket")
    graph.add_edge("jira_ticket", "trusted_memory")
    graph.add_edge("trusted_memory", END)
    return graph.compile()
