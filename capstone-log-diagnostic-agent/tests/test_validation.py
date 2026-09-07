from log_diagnostic_agent.models import (
    DiagnosisReport,
    Evidence,
    EvidenceCategory,
    EvidenceSource,
)
from log_diagnostic_agent.validation import validate_diagnosis


def _e(eid, source, category):
    return Evidence(
        evidence_id=eid,
        source=source,
        category=category,
        summary="test",
        content="test",
    )


def test_retrieval_only_context_cannot_validate_current_root_cause():
    evidence = [
        _e("E1", EvidenceSource.CONFLUENCE, EvidenceCategory.REFERENCE),
        _e("E2", EvidenceSource.VALIDATED_INCIDENT, EvidenceCategory.HISTORICAL),
    ]
    report = DiagnosisReport(
        incident_id="X",
        root_cause_status="probable",
        immediate_failure="timeout",
        probable_root_cause="pool exhaustion",
        confidence=0.8,
        evidence_ids=["E1", "E2"],
    )
    result = validate_diagnosis(report, evidence)
    assert not result.valid


def test_two_current_operational_sources_can_validate_probable_diagnosis():
    evidence = [
        _e("E1", EvidenceSource.LOG, EvidenceCategory.OPERATIONAL),
        _e("E2", EvidenceSource.METRICS, EvidenceCategory.OPERATIONAL),
    ]
    report = DiagnosisReport(
        incident_id="X",
        root_cause_status="probable",
        immediate_failure="timeout",
        probable_root_cause="pool exhaustion",
        confidence=0.8,
        evidence_ids=["E1", "E2"],
    )
    result = validate_diagnosis(report, evidence)
    assert result.valid
    assert result.validation_status == "validated"


def test_empty_tool_results_do_not_count_as_operational_support():
    evidence = [
        _e("E1", EvidenceSource.LOG, EvidenceCategory.OPERATIONAL),
        _e("E2", EvidenceSource.METRICS, EvidenceCategory.OPERATIONAL),
    ]
    evidence[1].substantive = False
    report = DiagnosisReport(
        incident_id="X",
        root_cause_status="probable",
        immediate_failure="timeout",
        probable_root_cause="pool exhaustion",
        confidence=0.8,
        evidence_ids=["E1", "E2"],
    )
    assert not validate_diagnosis(report, evidence).valid


def test_agent_cannot_self_confirm_before_human_review():
    evidence = [
        _e("E1", EvidenceSource.LOG, EvidenceCategory.OPERATIONAL),
        _e("E2", EvidenceSource.SOURCE_CODE, EvidenceCategory.OPERATIONAL),
    ]
    report = DiagnosisReport(
        incident_id="X",
        root_cause_status="confirmed",
        immediate_failure="timeout",
        probable_root_cause="pool exhaustion",
        confidence=0.8,
        evidence_ids=["E1", "E2"],
    )
    assert not validate_diagnosis(report, evidence).valid
