from __future__ import annotations

import json
import os
import time
import webbrowser
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from .models import HumanReview


class ReviewUIError(RuntimeError):
    """Raised when the local SignalDesk review console cannot be reached."""


def build_ui_review_item(state: dict, report: dict) -> dict:
    """Translate diagnostic graph state into the SignalDesk review contract."""
    incident = state["incident"]
    hypotheses = state.get("hypotheses", [])
    branches = {
        item.get("hypothesis_id"): item for item in state.get("branch_results", [])
    }
    critic = state.get("critic") or {}
    selected_id = critic.get("selected_hypothesis_id")

    diagnoses = []
    for index, hypothesis in enumerate(hypotheses, 1):
        diagnosis_id = hypothesis.get("hypothesis_id") or f"H{index}"
        branch = branches.get(diagnosis_id, {})
        statement = str(hypothesis.get("statement") or "Unspecified diagnosis")
        signals = list(branch.get("missing_information", []))
        if diagnosis_id == selected_id:
            signals.insert(0, "Selected by the critic")
        diagnoses.append(
            {
                "id": diagnosis_id,
                "title": statement[:160],
                "summary": branch.get("conclusion") or statement,
                # The selected diagnosis uses the evidence-gated report value. This
                # is the same value later delivered to Jira.
                "confidence": float(
                    report["confidence"]
                    if diagnosis_id == selected_id
                    else branch.get("score", hypothesis.get("confidence", 0))
                ),
                "evidenceIds": list(
                    report.get("evidence_ids", [])
                    if diagnosis_id == selected_id
                    else (
                        branch.get("supporting_evidence_ids")
                        or hypothesis.get("supporting_evidence_ids", [])
                    )
                ),
                "signals": signals,
            }
        )
    if not diagnoses:
        diagnoses.append(
            {
                "id": selected_id or "H1",
                "title": report["probable_root_cause"][:160],
                "summary": report["probable_root_cause"],
                "confidence": float(report["confidence"]),
                "evidenceIds": list(report.get("evidence_ids", [])),
                "signals": list(report.get("missing_information", [])),
            }
        )

    change_diagnosis_id = selected_id or diagnoses[0]["id"]
    suggested_changes = [
        {
            "id": f"CHANGE-{index}",
            "diagnosisId": change_diagnosis_id,
            "title": action.splitlines()[0][:160],
            "detail": action,
            "risk": "Medium",
            "category": "Agent recommendation",
            "implementation": action,
            "validation": "Validate the change in a non-production environment and monitor the original failure signal.",
            "rollback": "Revert the change if the original signal worsens or a regression appears.",
        }
        for index, action in enumerate(report.get("recommended_actions", []), 1)
    ]

    evidence_events = []
    similar_incidents = []
    for item in state.get("evidence", []):
        collected = str(item.get("collected_at") or "")
        source = str(item.get("source") or "unknown")
        summary = str(item.get("summary") or "Evidence collected")
        content = str(item.get("content") or "").strip()
        evidence_events.append(
            {
                "id": item.get("evidence_id") or f"E{len(evidence_events) + 1}",
                "time": collected,
                "source": source.replace("_", " ").title(),
                "summary": summary,
                # Preserve bounded source/log excerpts instead of reducing the
                # review package to a generic tool summary.
                "detail": (content or summary)[:4000],
                "tone": "warning" if source in {"log", "metrics"} else "info",
            }
        )
        if source == "validated_incident":
            try:
                matches = json.loads(str(item.get("content") or "[]"))
            except json.JSONDecodeError:
                matches = []
            for match in matches if isinstance(matches, list) else []:
                record = match.get("record") or {}
                similar_incidents.append(
                    {
                        "id": str(record.get("incident_id") or item.get("evidence_id")),
                        "title": str(
                            record.get("validated_diagnosis")
                            or record.get("symptoms")
                            or "Previously reviewed incident"
                        ),
                        "similarity": float(match.get("score") or 0.0),
                        "resolution": str(record.get("resolution") or "No resolution recorded"),
                        "age": "Previously reviewed",
                    }
                )

    now = datetime.now(timezone.utc).isoformat()
    application = str(incident.get("application") or "Unknown application")
    return {
        "incidentId": report["incident_id"],
        "title": report.get("immediate_failure") or incident.get("description", "Incident"),
        "application": application,
        "environment": str(incident.get("environment") or "Local"),
        "severity": "High" if incident.get("high_impact") else "Medium",
        "symptom": report.get("immediate_failure") or incident.get("description", ""),
        "createdAt": now,
        "payload": {
            "dataOrigin": "agent",
            "sourceProject": application,
            "scenarioBasis": "Generated from the current automated diagnostic run.",
            "detectedAt": now,
            "service": str(incident.get("component") or application),
            "owner": str(incident.get("owner") or "Unassigned"),
            "affected": str(incident.get("description") or report.get("immediate_failure", "")),
            "diagnoses": diagnoses,
            "suggestedChanges": suggested_changes,
            "similarIncidents": similar_incidents,
            "evidence": evidence_events,
        },
    }


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    bearer_token: str | None = None,
    timeout: float = 10.0,
) -> dict:
    encoded = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"content-type": "application/json", "accept": "application/json"}
    if bearer_token:
        headers["authorization"] = f"Bearer {bearer_token}"
    request = Request(
        url,
        data=encoded,
        method=method,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured local UI
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ReviewUIError(f"SignalDesk returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ReviewUIError(
            f"Cannot reach SignalDesk at {url}. Start the UI with 'cd ui; npm run dev'."
        ) from exc


def publish_jira_result(base_url: str, incident_id: str, ticket: dict) -> dict:
    """Publish the terminal Jira result so SignalDesk can replace its queued state."""
    base_url = base_url.rstrip("/") + "/"
    api_url = urljoin(
        base_url,
        f"api/reviews/{quote(incident_id, safe='')}/jira",
    )
    return _request_json(
        api_url,
        method="POST",
        body={"jira_ticket": ticket},
        bearer_token=os.getenv("SIGNALDESK_REVIEW_API_TOKEN") or None,
    )


def _review_from_ui_decisions(interrupt_payload: dict, decisions: list[dict]) -> HumanReview:
    diagnoses = {
        item["id"]: item for item in interrupt_payload["ui_review"]["payload"]["diagnoses"]
    }
    approved = [item for item in decisions if item.get("decision") == "approved"]
    reviewer = next(
        (str(item.get("reviewerName", "")).strip() for item in decisions if item.get("reviewerName")),
        "SignalDesk reviewer",
    )
    notes = "\n".join(
        f"{item.get('diagnosisId')}: {item.get('decision')} — {item.get('comments', '').strip()}"
        for item in decisions
    )
    if not approved:
        return HumanReview(decision="reject", reviewer=reviewer, notes=notes)

    critic = interrupt_payload.get("critic") or {}
    selected_id = critic.get("selected_hypothesis_id")
    chosen = next(
        (item for item in approved if item.get("diagnosisId") == selected_id),
        approved[0],
    )
    diagnosis = diagnoses[str(chosen["diagnosisId"])]
    can_confirm = (
        chosen.get("diagnosisId") == selected_id
        and interrupt_payload.get("automated_validation") == "validated"
    )
    return HumanReview(
        decision="confirm" if can_confirm else "correct",
        reviewer=reviewer,
        diagnosis_id=str(chosen["diagnosisId"]),
        diagnosis_confidence=float(diagnosis.get("confidence", 0)),
        evidence_ids=list(diagnosis.get("evidenceIds", [])),
        corrected_root_cause=None if can_confirm else diagnosis["summary"],
        actual_remediation=(
            "Approved for implementation in SignalDesk; implementation outcome is pending. "
            f"Reviewer comment: {chosen.get('comments', '').strip()}"
        ),
        notes=notes,
    )


def collect_review_in_ui(
    interrupt_payload: dict,
    base_url: str,
    *,
    poll_seconds: float = 2.0,
    browser_open: Callable[[str], object] = webbrowser.open,
) -> HumanReview:
    """Enqueue an interrupt, open its review modal, and wait for all decisions."""
    ui_review = interrupt_payload.get("ui_review")
    if not ui_review:
        raise ReviewUIError("The diagnostic workflow did not contain a SignalDesk payload")
    base_url = base_url.rstrip("/") + "/"
    api_url = urljoin(base_url, "api/reviews")
    requested_at = datetime.now(timezone.utc)
    _request_json(api_url, method="POST", body=ui_review)

    incident_id = str(ui_review["incidentId"])
    review_url = (
        f"{base_url}?incidentId={quote(incident_id, safe='')}&action=review"
    )
    browser_open(review_url)
    print("  > Review package saved to the SignalDesk queue.", flush=True)
    print(f"    Review URL: {review_url}", flush=True)
    print("  > The default browser was opened to the diagnosis decision dialog.", flush=True)
    print(
        "  > Waiting for every diagnosis to receive a decision and comment. "
        "Press Ctrl+C to stop; the checkpoint remains resumable.",
        flush=True,
    )

    required_ids = {item["id"] for item in ui_review["payload"]["diagnoses"]}
    while True:
        response = _request_json(api_url)
        review = next(
            (item for item in response.get("reviews", []) if item.get("incidentId") == incident_id),
            None,
        )
        if review:
            current = []
            for item in review.get("diagnosisDecisions", []):
                raw_created = str(item.get("createdAt") or "")
                try:
                    created_at = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if created_at >= requested_at:
                    current.append(item)
            decided_ids = {item.get("diagnosisId") for item in current}
            if required_ids and required_ids.issubset(decided_ids):
                print("  > SignalDesk submission received.", flush=True)
                for item in sorted(current, key=lambda value: str(value.get("diagnosisId"))):
                    print(
                        f"    {item.get('diagnosisId')}: {item.get('decision')} "
                        f"by {item.get('reviewerName')}",
                        flush=True,
                    )
                return _review_from_ui_decisions(interrupt_payload, current)
        time.sleep(max(0.25, poll_seconds))
