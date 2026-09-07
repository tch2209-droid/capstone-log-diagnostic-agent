import { env } from "cloudflare:workers";
import { ensureSchema } from "../../../../../db";

type JiraResult = {
  status?: "pending" | "created" | "existing" | "failed" | "not_configured" | "not_required";
  diagnosis_id?: string;
  diagnosisId?: string;
  issue_id?: string | null;
  issueId?: string | null;
  issue_key?: string | null;
  issueKey?: string | null;
  issue_url?: string | null;
  issueUrl?: string | null;
  error?: string | null;
};

type JiraCallbackEnvironment = {
  SIGNALDESK_REVIEW_API_TOKEN?: string;
};

function normalizeIssueUrl(value: string | null | undefined) {
  if (!value) return null;
  const markdownLink = value.match(/^\[[^\]]*\]\((https?:\/\/[^)]+)\)$/i);
  const candidate = markdownLink?.[1] ?? value;
  try {
    const parsed = new URL(candidate);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export async function POST(
  request: Request,
  context: { params: Promise<{ incidentId: string }> }
) {
  try {
    const configuredToken = (env as unknown as JiraCallbackEnvironment)
      .SIGNALDESK_REVIEW_API_TOKEN?.trim();
    if (
      configuredToken &&
      request.headers.get("authorization") !== `Bearer ${configuredToken}`
    ) {
      return Response.json({ error: "Valid service authentication is required" }, { status: 401 });
    }

    const { incidentId } = await context.params;
    const input = (await request.json()) as JiraResult & { jira_ticket?: JiraResult };
    const ticket = input.jira_ticket ?? input;
    const diagnosisId = ticket.diagnosis_id ?? ticket.diagnosisId;
    if (!diagnosisId || !ticket.status) {
      return Response.json(
        { error: "diagnosis_id and status are required" },
        { status: 400 }
      );
    }

    if (ticket.status === "not_required") {
      return Response.json({ status: "not_required" });
    }

    const status = ticket.status === "created" || ticket.status === "existing"
      ? "created"
      : ticket.status === "pending"
        ? "pending"
        : "failed";
    const issueId = ticket.issue_id ?? ticket.issueId ?? null;
    const issueKey = ticket.issue_key ?? ticket.issueKey ?? null;
    const issueUrl = normalizeIssueUrl(ticket.issue_url ?? ticket.issueUrl);
    const error = ticket.error ?? null;
    const updatedAt = new Date().toISOString();
    const db = await ensureSchema();
    const review = await db
      .prepare("SELECT incident_id FROM review_items WHERE incident_id = ?")
      .bind(incidentId)
      .first<{ incident_id: string }>();
    if (!review) {
      return Response.json({ error: "Incident review was not found" }, { status: 404 });
    }

    await db
      .prepare(
        `INSERT INTO jira_tickets (
          ticket_request_id, incident_id, diagnosis_id, status, jira_issue_id,
          jira_issue_key, jira_issue_url, last_error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(incident_id, diagnosis_id) DO UPDATE SET
          status=excluded.status,
          jira_issue_id=excluded.jira_issue_id,
          jira_issue_key=excluded.jira_issue_key,
          jira_issue_url=excluded.jira_issue_url,
          last_error=excluded.last_error,
          updated_at=excluded.updated_at`
      )
      .bind(
        crypto.randomUUID(),
        incidentId,
        diagnosisId,
        status,
        issueId,
        issueKey,
        issueUrl,
        error,
        updatedAt,
        updatedAt
      )
      .run();

    return Response.json({
      jiraTicket: { diagnosisId, status, issueId, issueKey, issueUrl, error },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to save Jira result";
    return Response.json({ error: message }, { status: 500 });
  }
}
