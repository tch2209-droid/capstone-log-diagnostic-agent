import { ensureSchema } from "../../../db";
import { seedReviews } from "../../../db/seed";
import type { JiraTicket, ReviewDecisionRecord, ReviewItem, ReviewPayload } from "../../types";

type ReviewRow = {
  incident_id: string;
  title: string;
  application: string;
  environment: string;
  severity: string;
  symptom: string;
  payload_json: string;
  review_status: ReviewItem["reviewStatus"];
  diagnosis_count: number;
  top_confidence: number;
  created_at: string;
  decision_id: string | null;
  diagnosis_id: string | null;
  decision: ReviewDecisionRecord["decision"] | null;
  reviewer_name: string | null;
  reviewer_email: string | null;
  comments: string | null;
  decision_created_at: string | null;
};

type DecisionRow = {
  decision_id: string;
  incident_id: string;
  diagnosis_id: string;
  decision: ReviewDecisionRecord["decision"];
  reviewer_name: string;
  reviewer_email: string | null;
  comments: string;
  created_at: string;
};

type JiraTicketRow = {
  incident_id: string;
  diagnosis_id: string;
  status: JiraTicket["status"];
  jira_issue_id: string | null;
  jira_issue_key: string | null;
  jira_issue_url: string | null;
  last_error: string | null;
};

async function seedMissingExamples(db: D1Database) {
  await db.batch(
    seedReviews.map((item) =>
      db
        .prepare(
          `INSERT OR IGNORE INTO review_items (
            incident_id, title, application, environment, severity, symptom,
            payload_json, review_status, diagnosis_count, top_confidence, created_at, updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
        )
        .bind(
          item.incidentId,
          item.title,
          item.application,
          item.environment,
          item.severity,
          item.symptom,
          JSON.stringify(item.payload),
          item.reviewStatus,
          item.diagnosisCount,
          item.topConfidence,
          item.createdAt,
          item.createdAt
        )
    )
  );
}

export async function GET() {
  try {
    const db = await ensureSchema();
    await seedMissingExamples(db);
    const result = await db
      .prepare(
        `SELECT r.*,
          d.decision_id, d.diagnosis_id, d.decision, d.reviewer_name,
          d.reviewer_email, d.comments, d.created_at AS decision_created_at
        FROM review_items r
        LEFT JOIN human_decisions d ON d.decision_id = (
          SELECT hd.decision_id FROM human_decisions hd
          WHERE hd.incident_id = r.incident_id
            AND datetime(hd.created_at) >= datetime(r.updated_at)
          ORDER BY hd.created_at DESC, hd.decision_id DESC LIMIT 1
        )
        ORDER BY CASE WHEN r.review_status = 'pending' THEN 0 ELSE 1 END,
          r.created_at DESC`
      )
      .all<ReviewRow>();

    const decisionResult = await db
      .prepare(
        `SELECT d.decision_id, d.incident_id, d.diagnosis_id, d.decision,
          d.reviewer_name, d.reviewer_email, d.comments, d.created_at
        FROM human_decisions d
        INNER JOIN review_items r ON r.incident_id = d.incident_id
        WHERE d.diagnosis_id IS NOT NULL
          AND datetime(d.created_at) >= datetime(r.updated_at)
        ORDER BY d.created_at DESC, d.decision_id DESC`
      )
      .all<DecisionRow>();

    const jiraResult = await db
      .prepare(
        `SELECT incident_id, diagnosis_id, status, jira_issue_id,
          jira_issue_key, jira_issue_url, last_error
        FROM jira_tickets`
      )
      .all<JiraTicketRow>();

    const decisionsByIncident = new Map<string, ReviewDecisionRecord[]>();
    const seenDiagnoses = new Set<string>();
    for (const row of decisionResult.results) {
      const key = `${row.incident_id}:${row.diagnosis_id}`;
      if (seenDiagnoses.has(key)) continue;
      seenDiagnoses.add(key);
      const current = decisionsByIncident.get(row.incident_id) ?? [];
      current.push({
        decisionId: row.decision_id,
        diagnosisId: row.diagnosis_id,
        decision: row.decision,
        reviewerName: row.reviewer_name,
        reviewerEmail: row.reviewer_email,
        comments: row.comments,
        createdAt: row.created_at,
      });
      decisionsByIncident.set(row.incident_id, current);
    }

    const jiraByIncident = new Map<string, JiraTicket[]>();
    for (const row of jiraResult.results) {
      const current = jiraByIncident.get(row.incident_id) ?? [];
      current.push({
        diagnosisId: row.diagnosis_id,
        status: row.status,
        issueId: row.jira_issue_id,
        issueKey: row.jira_issue_key,
        issueUrl: row.jira_issue_url,
        error: row.last_error,
      });
      jiraByIncident.set(row.incident_id, current);
    }

    const reviews: ReviewItem[] = result.results.map((row) => ({
      incidentId: row.incident_id,
      title: row.title,
      application: row.application,
      environment: row.environment,
      severity: row.severity,
      symptom: row.symptom,
      reviewStatus: row.review_status,
      diagnosisCount: row.diagnosis_count,
      topConfidence: row.top_confidence,
      createdAt: row.created_at,
      payload: JSON.parse(row.payload_json) as ReviewPayload,
      latestDecision: row.decision_id
        ? {
            decisionId: row.decision_id,
            diagnosisId: row.diagnosis_id,
            decision: row.decision!,
            reviewerName: row.reviewer_name!,
            reviewerEmail: row.reviewer_email,
            comments: row.comments!,
            createdAt: row.decision_created_at!,
          }
        : null,
      diagnosisDecisions: decisionsByIncident.get(row.incident_id) ?? [],
      jiraTickets: jiraByIncident.get(row.incident_id) ?? [],
    }));

    return Response.json({ reviews });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load reviews";
    return Response.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const input = (await request.json()) as Partial<ReviewItem>;
    if (!input.incidentId || !input.title || !input.application || !input.payload) {
      return Response.json(
        { error: "incidentId, title, application, and payload are required" },
        { status: 400 }
      );
    }
    const db = await ensureSchema();
    const diagnoses = input.payload.diagnoses ?? [];
    await db
      .prepare(
        `INSERT INTO review_items (
          incident_id, title, application, environment, severity, symptom,
          payload_json, review_status, diagnosis_count, top_confidence, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(incident_id) DO UPDATE SET
          title=excluded.title, application=excluded.application,
          environment=excluded.environment, severity=excluded.severity,
          symptom=excluded.symptom, payload_json=excluded.payload_json,
          review_status='pending',
          diagnosis_count=excluded.diagnosis_count,
          top_confidence=excluded.top_confidence, updated_at=CURRENT_TIMESTAMP`
      )
      .bind(
        input.incidentId,
        input.title,
        input.application,
        input.environment ?? "Unknown",
        input.severity ?? "Unclassified",
        input.symptom ?? "No symptom summary supplied",
        JSON.stringify(input.payload),
        diagnoses.length,
        Math.max(0, ...diagnoses.map((item) => item.confidence))
      )
      .run();
    return Response.json({ incidentId: input.incidentId }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to create review";
    return Response.json({ error: message }, { status: 500 });
  }
}
