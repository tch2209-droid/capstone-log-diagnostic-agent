import pytest

from log_diagnostic_agent.models import DiagnosisReport, HumanReview
from log_diagnostic_agent.review import apply_human_review, eligible_for_trusted_memory


def _report(validation_status="validated"):
    return DiagnosisReport(
        incident_id="INC-1",
        root_cause_status="probable",
        immediate_failure="request failed",
        probable_root_cause="draft cause",
        confidence=0.8,
        validation_status=validation_status,
    )


def test_confirmed_report_requires_remediation_and_is_memory_eligible():
    reviewed = apply_human_review(
        _report(),
        HumanReview(
            decision="confirm",
            reviewer="operator",
            actual_remediation="Restarted the failed dependency and verified recovery.",
        ),
    )
    assert reviewed.review_status == "confirmed"
    assert eligible_for_trusted_memory(reviewed)


def test_human_correction_can_replace_rejected_automated_draft():
    reviewed = apply_human_review(
        _report("rejected"),
        HumanReview(
            decision="correct",
            reviewer="operator",
            corrected_root_cause="Expired database certificate",
            actual_remediation="Rotated the certificate and verified connections.",
        ),
    )
    assert reviewed.validation_status == "validated"
    assert reviewed.review_status == "corrected"
    assert reviewed.probable_root_cause == "Expired database certificate"
    assert eligible_for_trusted_memory(reviewed)


def test_rejected_report_never_enters_trusted_memory():
    reviewed = apply_human_review(
        _report(), HumanReview(decision="reject", reviewer="operator")
    )
    assert reviewed.review_status == "rejected"
    assert not eligible_for_trusted_memory(reviewed)


def test_correction_requires_actual_remediation():
    with pytest.raises(ValueError):
        HumanReview(
            decision="correct",
            reviewer="operator",
            corrected_root_cause="Correct cause",
        )


def test_reviewer_and_remediation_cannot_be_whitespace():
    with pytest.raises(ValueError):
        HumanReview(decision="confirm", reviewer=" ", actual_remediation=" ")
