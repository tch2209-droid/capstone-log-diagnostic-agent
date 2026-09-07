import { env } from "cloudflare:workers";
import { ensureSchema } from "../../../db";

type RuntimeEnvironment = { SIGNALDESK_REVIEW_API_TOKEN?: string };

type OrchestrationInput = {
  eventId?: string;
  runId?: string;
  incidentId?: string;
  application?: string;
  eventType?: "run_started" | "node_started" | "node_completed" | "node_waiting" | "node_failed" | "run_completed";
  sequence?: number;
  node?: string | null;
  status?: "running" | "waiting" | "completed" | "failed";
  message?: string;
  details?: Record<string, unknown>;
  error?: string | null;
  createdAt?: string;
};

type RunRow = {
  run_id: string;
  incident_id: string;
  application: string;
  status: string;
  current_node: string | null;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  error: string | null;
};

type EventRow = {
  event_id: string;
  sequence: number;
  event_type: string;
  node: string | null;
  status: string;
  message: string;
  details_json: string;
  created_at: string;
};

export async function GET(request: Request) {
  try {
    const db = await ensureSchema();
    const runId = new URL(request.url).searchParams.get("runId");
    const run = runId
      ? await db.prepare("SELECT * FROM orchestration_runs WHERE run_id = ?").bind(runId).first<RunRow>()
      : await db
          .prepare(
            `SELECT * FROM orchestration_runs
             ORDER BY CASE WHEN status IN ('running', 'waiting') THEN 0 ELSE 1 END,
               updated_at DESC LIMIT 1`
          )
          .first<RunRow>();
    if (!run) return Response.json({ run: null, events: [] });

    const events = await db
      .prepare(
        `SELECT event_id, sequence, event_type, node, status, message, details_json, created_at
         FROM orchestration_events WHERE run_id = ? ORDER BY sequence ASC`
      )
      .bind(run.run_id)
      .all<EventRow>();

    return Response.json({
      run: {
        runId: run.run_id,
        incidentId: run.incident_id,
        application: run.application,
        status: run.status,
        currentNode: run.current_node,
        startedAt: run.started_at,
        updatedAt: run.updated_at,
        completedAt: run.completed_at,
        error: run.error,
      },
      events: events.results.map((event) => ({
        eventId: event.event_id,
        sequence: event.sequence,
        eventType: event.event_type,
        node: event.node,
        status: event.status,
        message: event.message,
        details: JSON.parse(event.details_json) as Record<string, unknown>,
        createdAt: event.created_at,
      })),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load orchestration";
    return Response.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const configuredToken = (env as unknown as RuntimeEnvironment).SIGNALDESK_REVIEW_API_TOKEN?.trim();
    if (configuredToken && request.headers.get("authorization") !== `Bearer ${configuredToken}`) {
      return Response.json({ error: "Valid service authentication is required" }, { status: 401 });
    }

    const input = (await request.json()) as OrchestrationInput;
    if (
      !input.eventId || !input.runId || !input.incidentId || !input.application ||
      !input.eventType || !input.sequence || !input.status || !input.message || !input.createdAt
    ) {
      return Response.json({ error: "Complete orchestration event data is required" }, { status: 400 });
    }

    const completedAt = input.status === "completed" || input.status === "failed" ? input.createdAt : null;
    const db = await ensureSchema();
    await db
      .prepare(
        `INSERT INTO orchestration_runs (
          run_id, incident_id, application, status, current_node, started_at,
          updated_at, completed_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
          incident_id=excluded.incident_id,
          application=excluded.application,
          status=excluded.status,
          current_node=COALESCE(excluded.current_node, orchestration_runs.current_node),
          updated_at=excluded.updated_at,
          completed_at=COALESCE(excluded.completed_at, orchestration_runs.completed_at),
          error=excluded.error`
      )
      .bind(
        input.runId, input.incidentId, input.application, input.status, input.node ?? null,
        input.createdAt, input.createdAt, completedAt, input.error ?? null
      )
      .run();
    await db
      .prepare(
        `INSERT OR IGNORE INTO orchestration_events (
          event_id, run_id, sequence, event_type, node, status, message, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .bind(
        input.eventId, input.runId, input.sequence, input.eventType, input.node ?? null,
        input.status, input.message, JSON.stringify(input.details ?? {}), input.createdAt
      )
      .run();

    return Response.json({ runId: input.runId, sequence: input.sequence }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to save orchestration event";
    return Response.json({ error: message }, { status: 500 });
  }
}
