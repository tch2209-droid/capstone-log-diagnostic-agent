from __future__ import annotations

from .models import DiagnosisReport, HumanReview, ReviewDecision


def apply_human_review(report: DiagnosisReport, review: HumanReview) -> DiagnosisReport:
    """Apply an explicit reviewer decision without mutating the original draft."""

    reviewed = report.model_copy(deep=True)
    reviewed.reviewer = review.reviewer
    reviewed.actual_remediation = review.actual_remediation
    if review.decision == ReviewDecision.REJECT:
        reviewed.review_status = "rejected"
        reviewed.root_cause_status = "insufficient_evidence"
        reviewed.confidence = min(reviewed.confidence, 0.4)
        if review.notes:
            reviewed.missing_information.append(review.notes)
        return reviewed

    if review.decision == ReviewDecision.CORRECT:
        reviewed.review_status = "corrected"
        reviewed.probable_root_cause = review.corrected_root_cause or reviewed.probable_root_cause
        # A correction is itself the authoritative human disposition. It may enter
        # trusted memory only with the reviewer and actual remediation fields below.
        reviewed.validation_status = "validated"
    else:
        reviewed.review_status = "confirmed"
    reviewed.root_cause_status = "confirmed"
    if review.notes:
        reviewed.recommended_actions.append(f"Reviewer note: {review.notes}")
    return reviewed


def eligible_for_trusted_memory(report: DiagnosisReport) -> bool:
    return (
        report.validation_status == "validated"
        and report.review_status in {"confirmed", "corrected"}
        and bool(report.reviewer)
        and bool(report.actual_remediation)
    )
