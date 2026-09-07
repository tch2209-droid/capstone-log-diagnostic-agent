from log_diagnostic_agent.models import JiraTicketResult
from log_diagnostic_agent.review_delivery import build_review_delivery_graph


class FakeJiraProvider:
    def __init__(self):
        self.diagnosis_ids = []
        self.reports = []

    def create_or_get_ticket(self, incident, report, review, diagnosis_id):
        self.diagnosis_ids.append(diagnosis_id)
        self.reports.append(report)
        return JiraTicketResult(
            status="created",
            diagnosis_id=diagnosis_id,
            issue_id="10001",
            issue_key="SCRUM-7",
            issue_url="https://agentic-dev-tacme.atlassian.net/browse/SCRUM-7",
        )


class FakeIncidentMemory:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def search(self, query, top_k=3, application=None):
        return []


def test_review_delivery_graph_creates_only_approved_diagnoses():
    provider = FakeJiraProvider()
    memory = FakeIncidentMemory()
    graph = build_review_delivery_graph(provider, memory)
    result = graph.invoke(
        {
            "incident": {
                "incidentId": "INC-42",
                "title": "Checkout timeout",
                "application": "Checkout",
                "symptom": "Requests time out",
            },
            "payload": {
                "diagnoses": [
                    {"id": "D1", "title": "Pool exhausted", "summary": "No slots", "confidence": 0.9, "evidenceIds": ["E1"]},
                    {"id": "D2", "title": "DNS", "summary": "Lookup delay", "confidence": 0.5, "evidenceIds": ["E2"]},
                ],
                "suggestedChanges": [
                    {"id": "C1", "diagnosisId": "D1", "title": "Bound concurrency", "detail": "Add a semaphore"}
                ],
                "evidence": [
                    {
                        "id": "E1",
                        "source": "Source Code",
                        "summary": "Pool acquisition has no bound",
                        "detail": "Checkout.java:42: pool.acquire();",
                    }
                ],
            },
            "decisions": [
                {"diagnosisId": "D1", "decision": "approved", "reviewerName": "Ada", "comments": "Proceed"},
                {"diagnosisId": "D2", "decision": "rejected", "reviewerName": "Ada", "comments": "Weak evidence"},
            ],
        }
    )
    assert provider.diagnosis_ids == ["D1"]
    assert provider.reports[0].confidence == 0.9
    assert provider.reports[0].evidence_details[0].detail == "Checkout.java:42: pool.acquire();"
    assert result["jira_tickets"][0]["issue_key"] == "SCRUM-7"
    assert result["memory_admission"]["status"] == "admitted"
    assert len(memory.records) == 1
    record = memory.records[0]
    assert record.incident_id == "INC-42"
    assert record.metadata["jira_issue_keys"] == ["SCRUM-7"]
    assert record.metadata["jira_issue_urls"] == [
        "https://agentic-dev-tacme.atlassian.net/browse/SCRUM-7"
    ]
