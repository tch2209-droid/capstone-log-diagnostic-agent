import { sql } from "drizzle-orm";
import { index, integer, real, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const reviewItems = sqliteTable("review_items", {
  incidentId: text("incident_id").primaryKey(),
  title: text("title").notNull(),
  application: text("application").notNull(),
  environment: text("environment").notNull(),
  severity: text("severity").notNull(),
  symptom: text("symptom").notNull(),
  payloadJson: text("payload_json").notNull(),
  reviewStatus: text("review_status").notNull().default("pending"),
  diagnosisCount: integer("diagnosis_count").notNull().default(1),
  topConfidence: real("top_confidence").notNull().default(0),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const humanDecisions = sqliteTable("human_decisions", {
  decisionId: text("decision_id").primaryKey(),
  incidentId: text("incident_id")
    .notNull()
    .references(() => reviewItems.incidentId),
  diagnosisId: text("diagnosis_id"),
  decision: text("decision").notNull(),
  reviewerUserId: text("reviewer_user_id").notNull(),
  reviewerName: text("reviewer_name").notNull(),
  reviewerEmail: text("reviewer_email"),
  comments: text("comments").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const jiraTickets = sqliteTable(
  "jira_tickets",
  {
    ticketRequestId: text("ticket_request_id").primaryKey(),
    incidentId: text("incident_id")
      .notNull()
      .references(() => reviewItems.incidentId),
    diagnosisId: text("diagnosis_id").notNull(),
    status: text("status").notNull().default("pending"),
    jiraIssueId: text("jira_issue_id"),
    jiraIssueKey: text("jira_issue_key"),
    jiraIssueUrl: text("jira_issue_url"),
    lastError: text("last_error"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [uniqueIndex("jira_tickets_incident_diagnosis_idx").on(table.incidentId, table.diagnosisId)]
);

export const orchestrationRuns = sqliteTable(
  "orchestration_runs",
  {
    runId: text("run_id").primaryKey(),
    incidentId: text("incident_id").notNull(),
    application: text("application").notNull(),
    status: text("status").notNull().default("running"),
    currentNode: text("current_node"),
    startedAt: text("started_at").notNull(),
    updatedAt: text("updated_at").notNull(),
    completedAt: text("completed_at"),
    error: text("error"),
  },
  (table) => [index("orchestration_runs_updated_idx").on(table.updatedAt)]
);

export const orchestrationEvents = sqliteTable(
  "orchestration_events",
  {
    eventId: text("event_id").primaryKey(),
    runId: text("run_id")
      .notNull()
      .references(() => orchestrationRuns.runId),
    sequence: integer("sequence").notNull(),
    eventType: text("event_type").notNull(),
    node: text("node"),
    status: text("status").notNull(),
    message: text("message").notNull(),
    detailsJson: text("details_json").notNull().default("{}"),
    createdAt: text("created_at").notNull(),
  },
  (table) => [uniqueIndex("orchestration_events_run_sequence_idx").on(table.runId, table.sequence)]
);
