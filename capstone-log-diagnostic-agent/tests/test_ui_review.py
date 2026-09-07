from datetime import datetime, timedelta, timezone

from log_diagnostic_agent import ui_review


def _state():
    return {
        "incident": {
            "incident_id": "INC-42",
            "application": "InsuranceCallCenter",
            "description": "Calls are timing out",
        },
        "hypotheses": [
            {"hypothesis_id": "H1", "statement": "Worker exhaustion", "confidence": 0.84},
            {"hypothesis_id": "H2", "statement": "Provider throttling", "confidence": 0.61},
        ],
        "branch_results": [
            {
                "hypothesis_id": "H1",
                "score": 0.82,
                "supporting_evidence_ids": ["E1"],
                "conclusion": "Workers remain occupied by slow calls",
            },
            {
                "hypothesis_id": "H2",
                "score": 0.58,
                "supporting_evidence_ids": ["E2"],
                "conclusion": "The provider may be applying a rate limit",
            },
        ],
        "critic": {"selected_hypothesis_id": "H1"},
        "evidence": [
            {
                "evidence_id": "E1",
                "source": "source_code",
                "summary": "Outbound calls have no timeout",
                "content": "InsuranceClient.java:42: client.execute(request);",
            }
        ],
    }


def _report():
    return {
        "incident_id": "INC-42",
        "immediate_failure": "Calls are timing out",
        "probable_root_cause": "Worker exhaustion",
        "confidence": 0.82,
        "evidence_ids": ["E1"],
        "recommended_actions": ["Bound outbound call duration and add cancellation."],
        "missing_information": [],
    }


def test_build_ui_review_item_includes_all_diagnoses_and_changes():
    item = ui_review.build_ui_review_item(_state(), _report())

    assert item["incidentId"] == "INC-42"
    assert [diagnosis["id"] for diagnosis in item["payload"]["diagnoses"]] == ["H1", "H2"]
    assert item["payload"]["suggestedChanges"][0]["diagnosisId"] == "H1"
    assert item["payload"]["evidence"][0]["id"] == "E1"
    assert item["payload"]["evidence"][0]["summary"] == "Outbound calls have no timeout"
    assert "InsuranceClient.java:42" in item["payload"]["evidence"][0]["detail"]


def test_selected_diagnosis_uses_evidence_gated_report_confidence_and_evidence():
    state = _state()
    state["branch_results"][0]["score"] = 0.91
    report = _report()
    report["confidence"] = 0.76

    item = ui_review.build_ui_review_item(state, report)

    selected = item["payload"]["diagnoses"][0]
    assert selected["confidence"] == 0.76
    assert selected["evidenceIds"] == report["evidence_ids"]


def test_ui_approval_of_selected_diagnosis_resumes_as_confirmation():
    item = ui_review.build_ui_review_item(_state(), _report())
    payload = {
        "automated_validation": "validated",
        "critic": {"selected_hypothesis_id": "H1"},
        "ui_review": item,
    }
    review = ui_review._review_from_ui_decisions(
        payload,
        [
            {
                "diagnosisId": "H1",
                "decision": "approved",
                "reviewerName": "Ada",
                "comments": "Proceed after canary validation",
            },
            {
                "diagnosisId": "H2",
                "decision": "rejected",
                "reviewerName": "Ada",
                "comments": "No rate-limit response was observed",
            },
        ],
    )

    assert review.decision.value == "confirm"
    assert review.reviewer == "Ada"
    assert review.diagnosis_id == "H1"
    assert review.diagnosis_confidence == 0.82
    assert review.evidence_ids == ["E1"]
    assert "implementation outcome is pending" in review.actual_remediation


def test_alternate_approval_resumes_as_diagnosis_specific_correction():
    item = ui_review.build_ui_review_item(_state(), _report())
    payload = {
        "automated_validation": "validated",
        "critic": {"selected_hypothesis_id": "H1"},
        "ui_review": item,
    }
    review = ui_review._review_from_ui_decisions(
        payload,
        [
            {"diagnosisId": "H1", "decision": "rejected", "reviewerName": "Ada", "comments": "Not supported"},
            {"diagnosisId": "H2", "decision": "approved", "reviewerName": "Ada", "comments": "Provider confirmed throttling"},
        ],
    )

    assert review.decision.value == "correct"
    assert review.diagnosis_id == "H2"
    assert review.corrected_root_cause == "The provider may be applying a rate limit"


def test_collect_review_opens_deep_link_and_waits_for_current_decisions(monkeypatch):
    item = ui_review.build_ui_review_item(_state(), _report())
    payload = {
        "automated_validation": "validated",
        "critic": {"selected_hypothesis_id": "H1"},
        "ui_review": item,
    }
    now = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    calls = []

    def fake_request(url, *, method="GET", body=None):
        calls.append((method, url, body))
        if method == "POST":
            return {"incidentId": "INC-42"}
        return {
            "reviews": [
                {
                    "incidentId": "INC-42",
                    "diagnosisDecisions": [
                        {"diagnosisId": "H1", "decision": "approved", "reviewerName": "Ada", "comments": "Proceed", "createdAt": now},
                        {"diagnosisId": "H2", "decision": "rejected", "reviewerName": "Ada", "comments": "Unsupported", "createdAt": now},
                    ],
                }
            ]
        }

    opened = []
    monkeypatch.setattr(ui_review, "_request_json", fake_request)
    monkeypatch.setattr(ui_review.time, "sleep", lambda _: None)

    review = ui_review.collect_review_in_ui(
        payload,
        "http://127.0.0.1:3000",
        browser_open=opened.append,
    )

    assert calls[0][0] == "POST"
    assert opened == ["http://127.0.0.1:3000/?incidentId=INC-42&action=review"]
    assert review.decision.value == "confirm"


def test_publish_jira_result_posts_terminal_result_with_service_token(monkeypatch):
    calls = []

    def fake_request(url, *, method="GET", body=None, bearer_token=None):
        calls.append((url, method, body, bearer_token))
        return {"jiraTicket": {"status": "created"}}

    monkeypatch.setenv("SIGNALDESK_REVIEW_API_TOKEN", "test-token")
    monkeypatch.setattr(ui_review, "_request_json", fake_request)
    ticket = {
        "status": "created",
        "diagnosis_id": "H1",
        "issue_id": "10005",
        "issue_key": "SCRUM-6",
        "issue_url": "https://agentic-dev-tacme.atlassian.net/browse/SCRUM-6",
        "error": None,
    }

    ui_review.publish_jira_result("http://127.0.0.1:3000", "INC-42", ticket)

    assert calls == [
        (
            "http://127.0.0.1:3000/api/reviews/INC-42/jira",
            "POST",
            {"jira_ticket": ticket},
            "test-token",
        )
    ]
