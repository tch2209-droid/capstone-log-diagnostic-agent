from log_diagnostic_agent import orchestration_ui


def test_live_reporter_opens_deep_link_and_publishes_node_events(monkeypatch):
    calls = []
    sleeps = []
    opened = []

    def fake_request(url, *, method="GET", body=None, bearer_token=None, timeout=10.0):
        calls.append((url, method, body, bearer_token, timeout))
        return {"runId": body["runId"]}

    monkeypatch.setenv("SIGNALDESK_REVIEW_API_TOKEN", "service-token")
    monkeypatch.setattr(orchestration_ui, "_request_json", fake_request)
    reporter = orchestration_ui.OrchestrationUIReporter(
        "http://127.0.0.1:3000",
        "thread 42",
        {"incident_id": "INC-42", "application": "Claims"},
        browser_open=opened.append,
        sleep=sleeps.append,
    )
    state = {"evidence": [], "step_count": 0, "tool_call_count": 0}

    reporter.start(state)
    reporter.node_started("triage", state)
    reporter.node_completed("triage", state, {"evidence": [{"evidence_id": "E1"}]})

    assert opened == ["http://127.0.0.1:3000/orchestration?runId=thread%2042"]
    assert [call[2]["eventType"] for call in calls] == [
        "run_started",
        "node_started",
        "node_completed",
    ]
    assert [call[2]["sequence"] for call in calls] == [1, 2, 3]
    assert calls[-1][2]["details"]["evidenceCount"] == 1
    assert calls[-1][3:] == ("service-token", 2.0)
    assert calls[-1][2]["details"]["activityTitle"] == "Captured E1"
    assert calls[-1][2]["details"]["activityFacts"][1] == {"label": "Usable", "value": "Limited"}
    assert sleeps == [1.0]


def test_live_reporter_is_best_effort_when_ui_is_unavailable(monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise orchestration_ui.ReviewUIError("offline")

    monkeypatch.setattr(orchestration_ui, "_request_json", unavailable)
    reporter = orchestration_ui.OrchestrationUIReporter(
        "http://127.0.0.1:3000",
        "thread-42",
        {"incident_id": "INC-42", "application": "Claims"},
        delay_seconds=0,
        browser_open=lambda _: None,
    )

    reporter.node_started("triage", {})
    reporter.node_started("supervisor", {})

    assert capsys.readouterr().out.count("Live orchestration UI unavailable") == 1
