import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const templateRoot = new URL("../", import.meta.url);

test("defines the complete incident review console", async () => {
  const [page, layout, consoleSource, seed, decisionRoute] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/review-console.tsx", import.meta.url), "utf8"),
    readFile(new URL("../db/seed.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/reviews/[incidentId]/decision/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /SignalDesk — Incident Review/);
  assert.match(layout, /og-orchestration\.png/);
  assert.match(page, /ReviewConsole/);
  assert.match(consoleSource, /Incident review queue/);
  assert.match(consoleSource, />Incident ID</);
  assert.match(consoleSource, />Jira</);
  assert.match(consoleSource, /jira-column-cell/);
  assert.match(consoleSource, /Evidence to verify before deciding/);
  assert.match(consoleSource, /entry\.detail/);
  assert.match(consoleSource, /ticket\.issueKey \?\? "Open ticket"/);
  assert.match(consoleSource, /View details/);
  assert.match(consoleSource, /detailIncident/);
  assert.match(consoleSource, /reviewIncident/);
  assert.match(consoleSource, /role="dialog"/);
  assert.match(consoleSource, /Candidate diagnoses/);
  assert.match(consoleSource, /Suggested changes/);
  assert.match(consoleSource, /Similar incidents/);
  assert.match(consoleSource, /Implementation details/);
  assert.match(consoleSource, /Suggested code/);
  assert.match(consoleSource, /Affected files/);
  assert.match(consoleSource, /Decide on each diagnosis independently/);
  assert.match(consoleSource, /comments: diagnosisDrafts\[diagnosis\.id\]\.comments\.trim\(\)/);
  assert.match(consoleSource, /setReviewIncident\(null\)/);
  assert.match(consoleSource, /search\.get\("incidentId"\)/);
  assert.match(consoleSource, /search\.get\("action"\) === "review"/);
  assert.match(decisionRoute, /submissions\.length !== payload\.diagnoses\.length/);
  assert.match(decisionRoute, /savedDecisions\.map/);
  assert.match(decisionRoute, /diagnosis_id/);
  assert.match(consoleSource, /Submit \$\{reviewIncident\.payload\.diagnoses\.length\}/);
  assert.match(seed, /Checkout requests timing out/);
  assert.match(seed, /Urgent agent messages remain queued/);
  assert.match(seed, /Agent updates fail during address validation/);
  assert.match(seed, /Call-center notifications rejected by message service/);
  assert.match(seed, /Address API error rate spikes under provider throttling/);
  assert.match(seed, /Agent API latency rises while metrics snapshots are written/);
  assert.match(seed, /Active-agent picker returns no assignments/);
  assert.ok((seed.match(/incidentId:/g) ?? []).length >= 9);
  assert.match(seed, /dataOrigin: "synthetic"/);
  assert.match(consoleSource, /Synthetic scenario/);
  assert.doesNotMatch(`${page}${layout}${consoleSource}`, /human[- ](?:in[- ]the[- ]loop|review|decision)/i);
  assert.doesNotMatch(`${page}${layout}`, /codex-preview|Your site is taking shape/);
});

test("qualifies joined review-history columns for SQLite", async () => {
  const reviewsRoute = await readFile(new URL("../app/api/reviews/route.ts", import.meta.url), "utf8");
  assert.match(reviewsRoute, /SELECT d\.decision_id, d\.incident_id, d\.diagnosis_id, d\.decision/);
  assert.doesNotMatch(reviewsRoute, /SELECT decision_id, incident_id, diagnosis_id, decision/);
});

test("includes every review decision and delegates Jira to the delivery service", async () => {
  const [consoleSource, hosting, packageJson, decisionRoute, jiraRoute, schema] = await Promise.all([
    readFile(new URL("../app/review-console.tsx", import.meta.url), "utf8"),
    readFile(new URL("../.openai/hosting.json", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../app/api/reviews/[incidentId]/decision/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/reviews/[incidentId]/jira/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../db/schema.ts", import.meta.url), "utf8"),
  ]);

  for (const label of ["Approved", "Rejected", "Already Addressed", "Duplicate", "Inconclusive"]) {
    assert.match(consoleSource, new RegExp(label));
  }
  assert.match(consoleSource, /Comments for/);
  assert.match(consoleSource, /Jira ticket pending/);
  assert.doesNotMatch(consoleSource, /LangGraph/i);
  assert.match(decisionRoute, /approvedDecisions/);
  assert.match(decisionRoute, /jira_tickets/);
  assert.match(decisionRoute, /ticketsFromResponse/);
  assert.match(decisionRoute, /function deliveryStatus/);
  assert.match(decisionRoute, /ticket\.status === "failed" \|\| ticket\.status === "not_configured"/);
  assert.match(decisionRoute, /jira_ticket/);
  assert.match(decisionRoute, /LANGGRAPH_REVIEW_API_URL/);
  assert.doesNotMatch(decisionRoute, /createJiraTicket|StreamableHTTPClientTransport/);
  assert.match(jiraRoute, /ON CONFLICT\(incident_id, diagnosis_id\) DO UPDATE/);
  assert.match(schema, /jiraTickets/);
  assert.match(hosting, /"d1": "DB"/);
  assert.doesNotMatch(packageJson, /modelcontextprotocol/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(access(new URL("../app/atlassian-mcp.ts", import.meta.url)));
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
  await assert.rejects(access(new URL("../public/favicon.svg", templateRoot)));
});

test("provides a separate interactive LangGraph capstone replay", async () => {
  const [header, page, demo, liveRoute, schema] = await Promise.all([
    readFile(new URL("../app/app-header.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/orchestration/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/orchestration/orchestration-demo.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/orchestration/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../db/schema.ts", import.meta.url), "utf8"),
  ]);

  assert.match(header, /Review console/);
  assert.match(header, /Orchestration demo/);
  assert.match(page, /Live orchestration/);
  assert.match(demo, /LangGraph orchestration/);
  assert.match(demo, /Play walkthrough/);
  assert.match(demo, /INC-PnCAgentInfo-007/);
  assert.match(demo, /SCRUM-6/);
  for (const node of [
    "triage",
    "supervisor",
    "execute_tool",
    "remember",
    "draft",
    "hypothesize",
    "branches",
    "critic",
    "evidence_gate",
    "human_review",
    "jira_ticket",
    "finalize",
  ]) {
    assert.match(demo, new RegExp(`id: "${node}"`));
  }
  assert.match(demo, /status: "pending"/);
  assert.match(demo, /status: "created"/);
  assert.match(demo, /Original console logging remains unchanged/);
  assert.match(demo, /api\/orchestration/);
  assert.match(demo, /700/);
  assert.match(demo, /1-second demo pacing/);
  assert.match(demo, /node-live-popup/);
  assert.match(demo, /activityTitle/);
  assert.match(liveRoute, /orchestration_events/);
  assert.match(liveRoute, /Valid service authentication is required/);
  assert.match(schema, /orchestrationRuns/);
  assert.match(schema, /orchestrationEvents/);
});
