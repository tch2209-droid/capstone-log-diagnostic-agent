from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EvidenceCategory(str, Enum):
    OPERATIONAL = "operational"
    REFERENCE = "reference"
    HISTORICAL = "historical"


class EvidenceSource(str, Enum):
    LOG = "log"
    METRICS = "metrics"
    SOURCE_CODE = "source_code"
    DEPLOYMENT = "deployment"
    CONFLUENCE = "confluence"
    VALIDATED_INCIDENT = "validated_incident"


class ToolResult(BaseModel):
    source: EvidenceSource
    category: EvidenceCategory
    summary: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    substantive: bool = True


class Evidence(BaseModel):
    evidence_id: str
    source: EvidenceSource
    category: EvidenceCategory
    summary: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    substantive: bool = True
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClaimType(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"
    UNKNOWN = "unknown"


class DiagnosticClaim(BaseModel):
    claim: str
    claim_type: ClaimType
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceDetail(BaseModel):
    """Human-readable evidence carried to review and Jira delivery."""

    evidence_id: str
    source: str
    summary: str
    detail: str


class Hypothesis(BaseModel):
    hypothesis_id: str = "H1"
    statement: str
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class HypothesisSet(BaseModel):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)
    multiple_plausible_causes: bool = False


class BranchAssessment(BaseModel):
    hypothesis_id: str
    depth: int = Field(default=1, ge=1, le=3)
    score: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conclusion: str


class CriticAssessment(BaseModel):
    selected_hypothesis_id: str | None = None
    converged: bool
    evidence_score: float = Field(ge=0, le=1)
    contradiction_score: float = Field(ge=0, le=1)
    unresolved_contradictions: list[str] = Field(default_factory=list)
    feedback: str


class DiagnosisReport(BaseModel):
    incident_id: str
    root_cause_status: Literal["confirmed", "probable", "insufficient_evidence"]
    immediate_failure: str
    probable_root_cause: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_details: list[EvidenceDetail] = Field(default_factory=list)
    claims: list[DiagnosticClaim] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    validation_status: Literal["pending", "validated", "rejected"] = "pending"
    review_status: Literal["pending", "confirmed", "corrected", "rejected"] = "pending"
    escalation_reasons: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    actual_remediation: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    validation_status: Literal["validated", "rejected"]
    reasons: list[str] = Field(default_factory=list)


class ReviewDecision(str, Enum):
    CONFIRM = "confirm"
    CORRECT = "correct"
    REJECT = "reject"


class HumanReview(BaseModel):
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=120)
    diagnosis_id: str | None = Field(default=None, max_length=120)
    diagnosis_confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    corrected_root_cause: str | None = Field(default=None, max_length=4000)
    actual_remediation: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_decision_fields(self):
        self.reviewer = self.reviewer.strip()
        if not self.reviewer:
            raise ValueError("Reviewer name cannot be blank")
        if self.corrected_root_cause is not None:
            self.corrected_root_cause = self.corrected_root_cause.strip() or None
        if self.actual_remediation is not None:
            self.actual_remediation = self.actual_remediation.strip() or None
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        if self.decision == ReviewDecision.CORRECT and not self.corrected_root_cause:
            raise ValueError("A corrected diagnosis is required for decision=correct")
        if self.decision in {ReviewDecision.CONFIRM, ReviewDecision.CORRECT}:
            if not self.actual_remediation:
                raise ValueError(
                    "The actual remediation outcome is required before trusted-memory admission"
                )
        return self


class JiraTicketResult(BaseModel):
    status: Literal[
        "not_required", "not_configured", "created", "existing", "failed"
    ]
    diagnosis_id: str | None = None
    issue_id: str | None = None
    issue_key: str | None = None
    issue_url: str | None = None
    error: str | None = None


class IncidentRecord(BaseModel):
    incident_id: str
    application: str
    component: str | None = None
    error_family: str | None = None
    symptoms: str
    validated_diagnosis: str
    evidence_summary: str
    resolution: str | None = None
    validation_status: Literal["validated"] = "validated"
    review_status: Literal["confirmed", "corrected"] = "confirmed"
    reviewed_by: str = "legacy_import"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimilarIncident(BaseModel):
    score: float
    record: IncidentRecord
