from pathlib import Path

from log_diagnostic_agent.config import Settings
from log_diagnostic_agent.models import DiagnosisReport, EvidenceDetail, HumanReview
from log_diagnostic_agent.tools.jira import (
    AtlassianRovoJiraProvider,
    DisabledJiraTicketProvider,
    _exception_summary,
    _find_issue,
    _result_values,
    _safe_label,
    jira_provider_from_settings,
)


def _report() -> DiagnosisReport:
    return DiagnosisReport(
        incident_id="INC-42",
        root_cause_status="probable",
        immediate_failure="Requests time out",
        probable_root_cause="Connection pool exhaustion",
        confidence=0.84,
        evidence_ids=["E1", "E2"],
        evidence_details=[
            EvidenceDetail(
                evidence_id="E1",
                source="Source Code",
                summary="Pool acquisition is unbounded",
                detail="OrderRepository.java:42: connectionPool.acquire();",
            ),
            EvidenceDetail(
                evidence_id="E2",
                source="Log",
                summary="Requests wait for connections",
                detail="WARN timed out waiting for connection",
            ),
        ],
        recommended_actions=["Bound concurrent requests", "Increase pool capacity"],
        validation_status="validated",
        review_status="confirmed",
        reviewer="Ada",
        actual_remediation="Limited concurrency",
    )


def test_disabled_provider_records_configuration_gap_without_throwing():
    result = DisabledJiraTicketProvider().create_or_get_ticket(
        {},
        _report(),
        HumanReview(
            decision="confirm", reviewer="Ada", actual_remediation="Limited concurrency"
        ),
        "H1",
    )
    assert result.status == "not_configured"
    assert "ATLASSIAN_MCP" in (result.error or "")


def test_provider_factory_requires_all_machine_credentials():
    settings = Settings(
        log_root=Path("data"),
        project_roots={"demo": Path("data")},
        use_pgvector=False,
        atlassian_mcp_url="https://mcp.atlassian.com/v2/mcp?tools=all",
        atlassian_mcp_auth_mode="api_token",
        atlassian_cloud_id="cloud-1",
    )
    assert isinstance(jira_provider_from_settings(settings), DisabledJiraTicketProvider)


def test_provider_factory_oauth_does_not_require_api_token():
    settings = Settings(
        log_root=Path("data"),
        project_roots={"demo": Path("data")},
        use_pgvector=False,
        atlassian_mcp_url="https://mcp.atlassian.com/v2/mcp",
        atlassian_mcp_auth_mode="oauth",
        atlassian_cloud_id="cloud-1",
    )

    provider = jira_provider_from_settings(settings)

    assert isinstance(provider, AtlassianRovoJiraProvider)
    assert provider.oauth_callback_port == 8765


def test_provider_factory_uses_configured_oauth_callback_port():
    settings = Settings(
        log_root=Path("data"),
        project_roots={"demo": Path("data")},
        use_pgvector=False,
        atlassian_mcp_url="https://mcp.atlassian.com/v2/mcp",
        atlassian_mcp_auth_mode="oauth",
        atlassian_oauth_callback_port=9876,
        atlassian_cloud_id="cloud-1",
    )

    provider = jira_provider_from_settings(settings)

    assert isinstance(provider, AtlassianRovoJiraProvider)
    assert provider.oauth_callback_port == 9876


def test_ticket_description_contains_approver_issue_and_changes():
    review = HumanReview(
        decision="confirm",
        reviewer="Ada Lovelace",
        actual_remediation="Limited concurrency",
        notes="Evidence supports the theory",
    )
    description = AtlassianRovoJiraProvider._description(
        {"application": "Checkout", "description": "Checkout is timing out"},
        _report(),
        review,
    )
    assert "Approver: Ada Lovelace" in description
    assert "Checkout is timing out" in description
    assert "Bound concurrent requests" in description
    assert "OrderRepository.java:42: connectionPool.acquire();" in description
    assert "Confidence: 84%" in description


def test_create_arguments_match_current_atlassian_schema():
    provider = AtlassianRovoJiraProvider(
        url="https://mcp.atlassian.com/v2/mcp",
        cloud_id="cloud-1",
        email="",
        api_token="",
        auth_mode="oauth",
        project_key="SCRUM",
        site_url="https://example.atlassian.net",
    )
    review = HumanReview(
        decision="confirm",
        reviewer="Ada Lovelace",
        actual_remediation="Limited concurrency",
    )

    arguments = provider._create_arguments(
        {"application": "Checkout"}, _report(), review, "signaldesk-inc-42-h1"
    )

    assert arguments["issueType"] == "Task"
    assert "issueTypeName" not in arguments
    assert arguments["contentFormat"] == "markdown"
    assert arguments["labels"] == [
        "signaldesk",
        "approved-diagnosis",
        "incident-inc-42",
        "signaldesk-inc-42-h1",
    ]
    assert arguments["summary"].startswith("[INC-42]")


def test_idempotency_label_and_issue_parser_are_stable():
    assert _safe_label("SignalDesk INC/42 H1") == "signaldesk-inc-42-h1"
    assert _find_issue({"issues": [{"id": "10001", "key": "SCRUM-7"}]}) == (
        "10001",
        "SCRUM-7",
    )


def test_nested_mcp_exception_reports_leaf_cause():
    error = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("Atlassian MCP returned HTTP 401")],
    )

    summary = _exception_summary(error)

    assert summary == "RuntimeError: Atlassian MCP returned HTTP 401"
    assert "TaskGroup" not in summary


def test_langchain_content_blocks_are_parsed_for_issue_keys():
    values = _result_values(
        [{"type": "text", "text": '{"issue": {"key": "SCRUM-8"}}'}]
    )

    assert _find_issue(values) == (None, "SCRUM-8")
