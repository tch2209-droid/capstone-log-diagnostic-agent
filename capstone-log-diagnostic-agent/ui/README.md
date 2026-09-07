# SignalDesk Incident Review

Private reviewer workspace for the capstone log diagnostic agent.

## Capabilities

- Filterable incident review queue
- Multiple diagnosis candidates with confidence, signals, and evidence IDs
- Diagnosis-linked suggested changes and risk labels
- Similar reviewed incidents and an evidence timeline
- Approved, Rejected, Already Addressed, Duplicate, and Inconclusive decisions
- Required reviewer comments and durable D1 audit records
- Approved diagnoses queued for the Python LangGraph Jira node
- A separate `/orchestration` capstone view with live agent events plus play, pause, step, node inspection,
  and a representative execution trace
- Authenticated reviewer attribution when hosted with Sites

## Local development

```powershell
npm install
Copy-Item .env.example .env
npm run dev
```

Open `http://localhost:3000`. The local D1 database is initialized and seeded on
the first `GET /api/reviews` request.

## Jira ownership

This TypeScript application does not connect to Atlassian MCP and does not hold an
Atlassian API token. It captures the reviewer decision and records an approved
diagnosis as pending orchestration work.

The Python `jira_ticket` node runs after LangGraph's reviewer checkpoint and owns the
MCP connection, API-token authentication, idempotency search, and Task creation in
project `SCRUM` (`Diagnostic Tickets - SignalDesk`). Atlassian credentials are
configured only in the Python runtime's root `.env`.

Set `LANGGRAPH_REVIEW_API_URL` and `SIGNALDESK_REVIEW_API_TOKEN` in the UI
runtime. The second value must match the Python runtime. Start the handoff service
from the repository root with `log-diagnose-review-server`. If it is temporarily
unavailable, the saved approval remains pending instead of being lost.

## API

- `GET /api/reviews` lists queued incidents and their latest decisions.
- `POST /api/reviews` creates or updates an incident review payload.
- `POST /api/reviews/{incidentId}/decision` records each diagnosis decision,
  comments, reviewer identity, and timestamp. It does not call MCP.
- `POST /api/orchestration` accepts authenticated graph-node telemetry from the
  Python runtime; `GET /api/orchestration?runId=...` powers the live demo view.

## Validation

```powershell
npm test
```

Drizzle migrations are stored in `drizzle/` and included in Sites deployments.
