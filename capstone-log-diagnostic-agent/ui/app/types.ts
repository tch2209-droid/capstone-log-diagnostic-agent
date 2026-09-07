export type DecisionValue =
  | "approved"
  | "rejected"
  | "already_addressed"
  | "duplicate"
  | "inconclusive";

export type Diagnosis = {
  id: string;
  title: string;
  summary: string;
  confidence: number;
  evidenceIds: string[];
  signals: string[];
};

export type SuggestedChange = {
  id: string;
  diagnosisId?: string;
  title: string;
  detail: string;
  risk: "Low" | "Medium" | "High";
  category: string;
  files?: string[];
  implementation?: string;
  code?: string;
  language?: string;
  validation?: string;
  rollback?: string;
};

export type SimilarIncident = {
  id: string;
  title: string;
  similarity: number;
  resolution: string;
  age: string;
};

export type EvidenceEvent = {
  id: string;
  time: string;
  source: string;
  summary?: string;
  detail: string;
  tone: "critical" | "warning" | "info";
};

export type ReviewPayload = {
  dataOrigin?: "synthetic" | "agent";
  sourceProject?: string;
  scenarioBasis?: string;
  detectedAt: string;
  service: string;
  owner: string;
  affected: string;
  diagnoses: Diagnosis[];
  suggestedChanges: SuggestedChange[];
  similarIncidents: SimilarIncident[];
  evidence: EvidenceEvent[];
};

export type ReviewDecisionRecord = {
  decisionId: string;
  diagnosisId: string | null;
  decision: DecisionValue;
  reviewerName: string;
  reviewerEmail: string | null;
  comments: string;
  createdAt: string;
};

export type JiraTicket = {
  diagnosisId: string;
  status: "pending" | "created" | "failed";
  issueId: string | null;
  issueKey: string | null;
  issueUrl: string | null;
  error: string | null;
};

export type ReviewItem = {
  incidentId: string;
  title: string;
  application: string;
  environment: string;
  severity: string;
  symptom: string;
  reviewStatus: DecisionValue | "pending";
  diagnosisCount: number;
  topConfidence: number;
  createdAt: string;
  payload: ReviewPayload;
  latestDecision: ReviewDecisionRecord | null;
  diagnosisDecisions: ReviewDecisionRecord[];
  jiraTickets: JiraTicket[];
};
