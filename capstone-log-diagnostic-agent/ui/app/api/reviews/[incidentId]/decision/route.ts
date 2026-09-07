import { env } from "cloudflare:workers";
import { ensureSchema } from "../../../../../db";
import type { DecisionValue, JiraTicket, ReviewPayload } from "../../../../types";

type ReviewRow = {
  title: string;
  application: string;
  environment: string;
  severity: string;
  symptom: string;
  payload_json: string;
};

type ReviewBridgeEnvironment = {
  LANGGRAPH_REVIEW_API_URL?: string;
  JIRA_DELIVERY_API_URL?: string;
  JIRA_BROWSE_BASE_URL?: string;
  SIGNALDESK_REVIEW_API_TOKEN?: string;
};

type OrchestrationTicket = {
  status?: "pending" | "created" | "existing" | "failed" | "not_configured";
  diagnosis_id?: string;
  issue_id?: string | null;
  issue_key?: string | null;
  issue_url?: string | null;
  error?: string | null;
};

type MemoryAdmission = {
  status?: "admitted" | "not_required" | "not_configured" | "failed";
  jira_issue_urls?: string[];
  error?: string | null;
};

type OrchestrationResponse = {
  jiraTickets?: OrchestrationTicket[];
  jira_tickets?: OrchestrationTicket[];
  jira_ticket?: OrchestrationTicket;
  memoryAdmission?: MemoryAdmission;
  memory_admission?: MemoryAdmission;
};

const decisions = new Set<DecisionValue>([
  "approved",
  "rejected",
  "already_addressed",
  "duplicate",
  "inconclusive",
]);

function reviewerFromRequest(request: Request) {
  const userId = request.headers.get("oai-authenticated-user-id");
  const email = request.headers.get("oai-authenticated-user-email");
  const encodedName = request.headers.get("oai-authenticated-user-full-name");
  const encoding = request.headers.get("oai-authenticated-user-full-name-encoding");
  let fullName: string | null = null;
  if (encodedName && encoding === "percent-encoded-utf-8") {
    try {
      fullName = decodeURIComponent(encodedName);
    } catch {
      fullName = null;
    }
  }
  if (userId && email) {
    return { userId, email, name: fullName ?? email };
  }

  const url = new URL(request.url);
  if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
    return {
      userId: "local-preview",
      email: null,
      name: request.headers.get("x-reviewer-name")?.trim() || "Local reviewer",
    };
  }
  return null;
}

function ticketsFromResponse(result: OrchestrationResponse) {
  if (Array.isArray(result.jiraTickets)) return result.jiraTickets;
  if (Array.isArray(result.jira_tickets)) return result.jira_tickets;
  return result.jira_ticket ? [result.jira_ticket] : [];
}

function normalizeIssueUrl(value: string | null | undefined) {
  if (!value) return null;
  const markdownLink = value.match(/^\[[^\]]*\]\((https?:\/\/[^)]+)\)$/i);
  return markdownLink?.[1] ?? value;
}

function deliveryStatus(ticket: OrchestrationTicket): JiraTicket["status"] {
  if (ticket.status === "created" || ticket.status === "existing") return "created";
  if (ticket.status === "failed" || ticket.status === "not_configured") return "failed";
  return "pending";
}

async function persistJiraResults(
  db: D1Database,
  incidentId: string,
  tickets: JiraTicket[]
) {
  if (!tickets.length) return;
  const updatedAt = new Date().toISOString();
  await db.batch(tickets.map((ticket) => db
    .prepare(
      `UPDATE jira_tickets SET status = ?, jira_issue_id = ?, jira_issue_key = ?,
        jira_issue_url = ?, last_error = ?, updated_at = ?
      WHERE incident_id = ? AND diagnosis_id = ?`
    )
    .bind(
      ticket.status,
      ticket.issueId,
      ticket.issueKey,
      ticket.issueUrl,
      ticket.error,
      updatedAt,
      incidentId,
      ticket.diagnosisId
    )));
}

export async function POST(
  request: Request,
  context: { params: Promise<{ incidentId: string }> }
) {
  try {
    const reviewer = reviewerFromRequest(request);
    if (!reviewer) {
      return Response.json({ error: "Sign in is required to submit a decision" }, { status: 401 });
    }

    const { incidentId } = await context.params;
    const input = (await request.json()) as {
      decisions?: Array<{
        diagnosisId?: string;
        decision?: DecisionValue;
        comments?: string;
      }>;
      decision?: DecisionValue;
      diagnosisId?: string | null;
      comments?: string;
    };
    const submissions = input.decisions?.length
      ? input.decisions
      : [{ diagnosisId: input.diagnosisId ?? undefined, decision: input.decision, comments: input.comments }];

    const db = await ensureSchema();
    const review = await db
      .prepare(
        `SELECT title, application, environment, severity, symptom, payload_json
        FROM review_items WHERE incident_id = ?`
      )
      .bind(incidentId)
      .first<ReviewRow>();
    if (!review) {
      return Response.json({ error: "Incident review was not found" }, { status: 404 });
    }

    const payload = JSON.parse(review.payload_json) as ReviewPayload;
    const diagnosisIds = new Set(payload.diagnoses.map((item) => item.id));
    const submittedIds = new Set(submissions.map((item) => item.diagnosisId));
    if (
      submissions.length !== payload.diagnoses.length ||
      submittedIds.size !== diagnosisIds.size ||
      [...diagnosisIds].some((id) => !submittedIds.has(id))
    ) {
      return Response.json(
        { error: "Record a decision for every diagnosis before submitting" },
        { status: 400 }
      );
    }
    for (const submission of submissions) {
      if (!submission.decision || !decisions.has(submission.decision)) {
        return Response.json({ error: "Choose a valid decision for every diagnosis" }, { status: 400 });
      }
      if (!submission.comments?.trim()) {
        return Response.json({ error: "Comments are required for every diagnosis" }, { status: 400 });
      }
    }

    const createdAt = new Date().toISOString();
    const savedDecisions = submissions.map((submission) => ({
      decisionId: crypto.randomUUID(),
      diagnosisId: submission.diagnosisId!,
      decision: submission.decision!,
      reviewerName: reviewer.name,
      reviewerEmail: reviewer.email,
      comments: submission.comments!.trim(),
      createdAt,
    }));
    const distinctDecisions = new Set(savedDecisions.map((item) => item.decision));
    const reviewStatus = distinctDecisions.size === 1
      ? savedDecisions[0].decision
      : "inconclusive";
    const approvedDecisions = savedDecisions.filter((item) => item.decision === "approved");

    await db.batch([
      ...savedDecisions.map((saved) => db
        .prepare(
          `INSERT INTO human_decisions (
            decision_id, incident_id, diagnosis_id, decision, reviewer_user_id,
            reviewer_name, reviewer_email, comments, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
        )
        .bind(
          saved.decisionId,
          incidentId,
          saved.diagnosisId,
          saved.decision,
          reviewer.userId,
          reviewer.name,
          reviewer.email,
          saved.comments,
          createdAt
        )),
      db
        .prepare(
          "UPDATE review_items SET review_status = ?, updated_at = ? WHERE incident_id = ?"
        )
        .bind(reviewStatus, createdAt, incidentId),
      ...approvedDecisions.map((approved) => db
        .prepare(
          `INSERT OR IGNORE INTO jira_tickets (
            ticket_request_id, incident_id, diagnosis_id, status, created_at, updated_at
          ) VALUES (?, ?, ?, 'pending', ?, ?)`
        )
        .bind(crypto.randomUUID(), incidentId, approved.diagnosisId, createdAt, createdAt)),
    ]);

    // Decision capture ends here. The Jira delivery service owns MCP.
    let jiraTickets: JiraTicket[] = approvedDecisions.map((approved) => ({
      diagnosisId: approved.diagnosisId,
      status: "pending",
      issueId: null,
      issueKey: null,
      issueUrl: null,
      error: null,
    }));
    let memoryAdmission: MemoryAdmission | null = null;

    const bridge = env as unknown as ReviewBridgeEnvironment;
    const bridgeUrl = bridge.JIRA_DELIVERY_API_URL?.trim()
      || bridge.LANGGRAPH_REVIEW_API_URL?.trim();
    const bridgeToken = bridge.SIGNALDESK_REVIEW_API_TOKEN?.trim();
    const jiraBrowseBaseUrl = (
      bridge.JIRA_BROWSE_BASE_URL?.trim()
      || "https://agentic-dev-tacme.atlassian.net/browse"
    ).replace(/\/$/, "");
    if (jiraTickets.length && bridgeUrl && bridgeToken) {
      try {
        const response = await fetch(
          `${bridgeUrl.replace(/\/$/, "")}/review-decisions`,
          {
            method: "POST",
            headers: {
              authorization: `Bearer ${bridgeToken}`,
              "content-type": "application/json",
            },
            body: JSON.stringify({
              incident: {
                incidentId,
                title: review.title,
                application: review.application,
                environment: review.environment,
                severity: review.severity,
                symptom: review.symptom,
              },
              payload,
              decisions: savedDecisions,
            }),
          }
        );
        if (!response.ok) {
          const detail = await response.text();
          throw new Error(`Jira service returned HTTP ${response.status}${detail ? `: ${detail.slice(0, 300)}` : ""}`);
        }
        const result = (await response.json()) as OrchestrationResponse;
        memoryAdmission = result.memoryAdmission ?? result.memory_admission ?? null;
        const deliveredByDiagnosis = new Map(
          ticketsFromResponse(result).map((ticket) => [ticket.diagnosis_id, ticket])
        );
        jiraTickets = approvedDecisions.map((approved) => {
          const ticket = deliveredByDiagnosis.get(approved.diagnosisId);
          if (!ticket) {
            return {
              diagnosisId: approved.diagnosisId,
              status: "pending" as const,
              issueId: null,
              issueKey: null,
              issueUrl: null,
              error: null,
            };
          }
          const issueUrl = normalizeIssueUrl(ticket.issue_url)
            ?? (ticket.issue_key ? `${jiraBrowseBaseUrl}/${encodeURIComponent(ticket.issue_key)}` : null);
          return {
            diagnosisId: ticket.diagnosis_id ?? approved.diagnosisId,
            status: deliveryStatus(ticket),
            issueId: ticket.issue_id ?? null,
            issueKey: ticket.issue_key ?? null,
            issueUrl,
            error: ticket.error ?? null,
          };
        });
        await persistJiraResults(db, incidentId, jiraTickets);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Jira delivery is still pending";
        jiraTickets = approvedDecisions.map((approved) => ({
          diagnosisId: approved.diagnosisId,
          status: "pending",
          issueId: null,
          issueKey: null,
          issueUrl: null,
          error: message,
        }));
        await persistJiraResults(db, incidentId, jiraTickets);
      }
    } else if (jiraTickets.length) {
      const message = !bridgeUrl
        ? "The Jira delivery service URL is not configured."
        : "The Jira delivery service token is not configured.";
      jiraTickets = approvedDecisions.map((approved) => ({
        diagnosisId: approved.diagnosisId,
        status: "pending",
        issueId: null,
        issueKey: null,
        issueUrl: null,
        error: message,
      }));
      await persistJiraResults(db, incidentId, jiraTickets);
    }

    return Response.json({
      decisions: savedDecisions,
      decision: savedDecisions[0],
      reviewStatus,
      jiraTickets,
      memoryAdmission,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to save decision";
    return Response.json({ error: message }, { status: 500 });
  }
}
