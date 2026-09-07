import { env } from "cloudflare:workers";
import { drizzle } from "drizzle-orm/d1";
import * as schema from "./schema";

const reviewItemsSql = `CREATE TABLE IF NOT EXISTS review_items (
  incident_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  application TEXT NOT NULL,
  environment TEXT NOT NULL,
  severity TEXT NOT NULL,
  symptom TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (
    review_status IN ('pending', 'approved', 'rejected', 'already_addressed', 'duplicate', 'inconclusive')
  ),
  diagnosis_count INTEGER NOT NULL DEFAULT 1,
  top_confidence REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)`;

const humanDecisionsSql = `CREATE TABLE IF NOT EXISTS human_decisions (
  decision_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  diagnosis_id TEXT,
  decision TEXT NOT NULL CHECK (
    decision IN ('approved', 'rejected', 'already_addressed', 'duplicate', 'inconclusive')
  ),
  reviewer_user_id TEXT NOT NULL,
  reviewer_name TEXT NOT NULL,
  reviewer_email TEXT,
  comments TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (incident_id) REFERENCES review_items(incident_id)
)`;

const decisionIndexSql = `CREATE INDEX IF NOT EXISTS human_decisions_incident_created_idx
  ON human_decisions (incident_id, created_at DESC)`;

const jiraTicketsSql = `CREATE TABLE IF NOT EXISTS jira_tickets (
  ticket_request_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  diagnosis_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'created', 'failed')),
  jira_issue_id TEXT,
  jira_issue_key TEXT,
  jira_issue_url TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (incident_id) REFERENCES review_items(incident_id),
  UNIQUE (incident_id, diagnosis_id)
)`;

const jiraTicketIndexSql = `CREATE INDEX IF NOT EXISTS jira_tickets_status_updated_idx
  ON jira_tickets (status, updated_at)`;

const orchestrationRunsSql = `CREATE TABLE IF NOT EXISTS orchestration_runs (
  run_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  application TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'waiting', 'completed', 'failed')),
  current_node TEXT,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  error TEXT
)`;

const orchestrationRunsUpdatedIndexSql = `CREATE INDEX IF NOT EXISTS orchestration_runs_updated_idx
  ON orchestration_runs (updated_at DESC)`;

const orchestrationEventsSql = `CREATE TABLE IF NOT EXISTS orchestration_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  node TEXT,
  status TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES orchestration_runs(run_id),
  UNIQUE (run_id, sequence)
)`;

const orchestrationEventsIndexSql = `CREATE INDEX IF NOT EXISTS orchestration_events_run_created_idx
  ON orchestration_events (run_id, sequence)`;

export function getD1() {
  if (!env.DB) {
    throw new Error(
      "Cloudflare D1 binding `DB` is unavailable. Set the `d1` field in .openai/hosting.json to `DB`."
    );
  }
  return env.DB;
}

export async function ensureSchema() {
  const d1 = getD1();
  await d1.batch([
    d1.prepare(reviewItemsSql),
    d1.prepare(humanDecisionsSql),
    d1.prepare(decisionIndexSql),
    d1.prepare(jiraTicketsSql),
    d1.prepare(jiraTicketIndexSql),
    d1.prepare(orchestrationRunsSql),
    d1.prepare(orchestrationRunsUpdatedIndexSql),
    d1.prepare(orchestrationEventsSql),
    d1.prepare(orchestrationEventsIndexSql),
  ]);
  return d1;
}

export function getDb() {
  return drizzle(getD1(), { schema });
}
