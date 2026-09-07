from __future__ import annotations

from .models import (
    DiagnosisReport,
    Evidence,
    EvidenceCategory,
    EvidenceSource,
    ClaimType,
    ValidationResult,
)


CURRENT_OPERATIONAL_SOURCES = {
    EvidenceSource.LOG,
    EvidenceSource.METRICS,
    EvidenceSource.SOURCE_CODE,
    EvidenceSource.DEPLOYMENT,
}


def validate_diagnosis(report: DiagnosisReport, evidence: list[Evidence]) -> ValidationResult:
    reasons: list[str] = []
    by_id = {item.evidence_id: item for item in evidence}

    missing = [eid for eid in report.evidence_ids if eid not in by_id]
    if missing:
        reasons.append(f"Report cites evidence that was never retrieved: {', '.join(missing)}")


    # Claim-level grounding: observed claims must cite retrieved evidence, and
    # every claim citation must exist. This keeps the validator deterministic
    # without asking a second LLM to judge its own unsupported statements.
    for claim in report.claims:
        claim_missing = [eid for eid in claim.evidence_ids if eid not in by_id]
        if claim_missing:
            reasons.append(
                f"Claim cites evidence that was never retrieved: {', '.join(claim_missing)}"
            )
        if claim.claim_type == ClaimType.OBSERVED and not claim.evidence_ids:
            reasons.append(f"Observed claim has no evidence: {claim.claim}")
        if claim.claim_type == ClaimType.OBSERVED and claim.evidence_ids:
            if not any(
                by_id[eid].substantive for eid in claim.evidence_ids if eid in by_id
            ):
                reasons.append(f"Observed claim cites no substantive evidence: {claim.claim}")

    cited = [by_id[eid] for eid in report.evidence_ids if eid in by_id]
    current_operational = [
        item
        for item in cited
        if item.category == EvidenceCategory.OPERATIONAL
        and item.source in CURRENT_OPERATIONAL_SOURCES
        and item.substantive
    ]

    if report.root_cause_status in {"probable", "confirmed"}:
        if not current_operational:
            reasons.append(
                "A probable/confirmed root cause must cite current operational evidence; "
                "Confluence or historical RAG context is not proof of the current incident."
            )
        distinct_sources = {item.source for item in current_operational}
        if len(current_operational) < 2 or len(distinct_sources) < 2:
            reasons.append(
                "A validated probable/confirmed diagnosis requires at least two current "
                "operational evidence items from distinct source types for independent support."
            )

    if report.root_cause_status == "confirmed" and report.review_status == "pending":
        reasons.append("The agent cannot mark a root cause confirmed before human review.")

    if report.root_cause_status == "insufficient_evidence" and report.confidence > 0.6:
        reasons.append("Insufficient-evidence reports should not claim high confidence.")

    if not report.probable_root_cause.strip():
        reasons.append("Root-cause field is empty.")

    if report.confidence > 0.95 and report.review_status == "pending":
        reasons.append("Pre-review diagnostic confidence cannot exceed 0.95.")

    valid = not reasons
    return ValidationResult(
        valid=valid,
        validation_status="validated" if valid else "rejected",
        reasons=reasons,
    )
