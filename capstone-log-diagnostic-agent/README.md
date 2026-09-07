# Application Log Diagnostic Agent

This project implements the supplied safety plan and Lucid architecture as a bounded, human-supervised LangGraph system. It reads application evidence locally, uses an OpenAI Codex model for reasoning, checkpoints investigation state in CockroachDB/PostgreSQL, and admits only human-confirmed or human-corrected outcomes to long-term incident memory.

## Implemented flow

```text
incident -> triage -> supervisor/ReAct -> read-only tool -> evidence catalog
                              |                         |
                              +-------- repeat --------+
                                           |
                                 selective hypotheses
                                           |
                              branch investigators -> critic
                                           |
                                  automated evidence gate
                                           |
                                  mandatory human review
                                           |
                              approved -> Jira MCP node
                                           |
                   confirmed/corrected -> trusted vector memory
                   rejected            -> no memory admission
```

Safety properties:

- local log access is restricted to `C:\AI_Repo\logs` by default;
- source search is restricted to the five configured projects;
- all agent tools are read-only and path traversal is rejected;
- tool output is bounded and common credentials are redacted;
- factual claims use evidence IDs, and probable diagnoses require two substantive current operational items from distinct source types;
- Confluence and prior incidents can suggest hypotheses but cannot prove the current cause or raise confidence;
- steps, tool calls, wall time, retries, branches, and branch depth are bounded;
- non-convergence, contradictory evidence, low confidence, high impact, policy sensitivity, and production-change requests are escalated;
- no automated result enters trusted memory until a person confirms/corrects it and records the actual remediation.
- Jira writes are deterministic post-review orchestration steps; the model and the TypeScript UI never receive a Jira write tool or Atlassian credentials.

## Local inputs

The default configuration reads these paths without modifying them:

- `C:\AI_Repo\logs`
- `C:\AI_Repo\AddressStandardizationAPI`
- `C:\AI_Repo\AgenticCourseFiles`
- `C:\AI_Repo\InsuranceAgentMessageService`
- `C:\AI_Repo\InsuranceCallCenter`
- `C:\AI_Repo\PropertyCasualtyInsuranceAgentInfo`

Override the project map with `PROJECT_ROOTS_JSON` if the directories move.

## Setup on Windows

Use Python 3.11, 3.12, or 3.13. From this directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[agent,postgres,mcp,dev]"
Copy-Item .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY` and `DATABASE_URL`. OAuth-based Jira
delivery needs `ATLASSIAN_CLOUD_ID`; API-token mode additionally needs
`ATLASSIAN_MCP_EMAIL` and `ATLASSIAN_MCP_API_TOKEN`. Real values are intentionally
absent from version-controlled files. The supplied CockroachDB connection string
can be used as `DATABASE_URL`; keep `sslmode=verify-full`.

All agent-facing prompt text is externalized in `agentinstructions.json`, including
the supervisor, hypothesis, branch, and critic prompts; graph feedback messages; tool
descriptions; and the default incident request. Change that file to tune agent behavior
without editing Python. Set `AGENT_INSTRUCTIONS_FILE` to load another JSON document.
Prompt templates use `$placeholder` tokens; keep the existing token names when editing.

Run an investigation using a path relative to the log root:

```powershell
.\.venv\Scripts\python.exe -m log_diagnostic_agent.langgraph_app `
  --application PropertyCasualtyInsuranceAgentInfo `
  --incident-id INC-LOCAL-001
```

Keep the SignalDesk UI running first (`cd ui; npm run dev`). At the LangGraph
human-review interrupt, the agent now adds the live incident to the review queue,
opens its decision dialog in the default browser, and waits for a decision there.
After every diagnosis has a disposition and comment, the durable graph resumes.
Set `SIGNALDESK_UI_URL` if the console is not at `http://127.0.0.1:3000`.
When the agent starts, it also opens `/orchestration` for the active thread and
streams graph-node progress to that page. For the capstone demo, each completed
node pauses for one second by default. Set
`SIGNALDESK_ORCHESTRATION_UI_ENABLED=false` to disable the live view or change
`SIGNALDESK_ORCHESTRATION_STEP_DELAY_SECONDS` to adjust the pacing.
Use `--terminal-review` only when the legacy PowerShell prompt is preferred.

To accept decisions from the SignalDesk UI, set the same
`SIGNALDESK_REVIEW_API_TOKEN` in the root and UI environments, then run:

```powershell
.\.venv\Scripts\python.exe -m log_diagnostic_agent.review_server --port 8090
```

Before a presentation, authenticate and verify the required Jira tools without
creating a ticket:

```powershell
.\.venv\Scripts\python.exe -m log_diagnostic_agent.atlassian_auth
```

OAuth opens Atlassian sign-in only when the operating-system credential vault has
no valid saved token. Completing this preflight keeps browser consent out of the
later human-decision submission.

Set the UI's `LANGGRAPH_REVIEW_API_URL` to that service. Its authenticated
`/review-decisions` endpoint invokes a Python LangGraph delivery graph; the UI
never receives Atlassian credentials or calls MCP.

If no log path is supplied, triage lists recent files matching the application.
Use `--non-interactive` to return the review payload without opening a browser or
accepting a decision; an API/UI can resume that durable thread later with the same
`thread_id`.

Run tests and the API-key-free synthetic demonstration:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m log_diagnostic_agent.demo
```

## Incident review UI

The `ui` directory contains the SignalDesk human-review console. It visualizes
the incident queue, multiple candidate diagnoses with confidence and evidence,
historically similar incidents, and diagnosis-specific suggested changes.

Reviewers select a diagnosis, choose **Approved**, **Rejected**,
**Already Addressed**, **Duplicate**, or **Inconclusive**, and enter required
comments. Each decision is written to the D1 `human_decisions` table with the
incident, diagnosis, reviewer identity, comments, and timestamp. The current
disposition is also stored on the review item. The private hosted UI uses the
authenticated Sites user headers; local preview uses a clearly labeled local
reviewer identity.

From `ui`, run:

```powershell
npm install
npm run dev
npm test
```

The agent or another ingestion service can enqueue a review by posting its
structured incident payload to `POST /api/reviews`. The UI reads the queue from
`GET /api/reviews` and saves decisions through
`POST /api/reviews/{incidentId}/decision`.

The UI route persists reviewer decisions, then hands approved diagnoses to the
Python orchestration endpoint. Jira creation is performed by a LangGraph
`jira_ticket` node. The main diagnostic graph also runs that node after its durable
`human_review` interrupt is resumed. The node
searches project `SCRUM` by a stable SignalDesk label before creating a Task, so
replaying a checkpoint does not intentionally create a duplicate. Its result is
stored in the LangGraph checkpoint as `jira_ticket`; a delivery failure is audited
without rolling back the human decision.

Jira delivery uses the LangChain MCP adapter from inside the deterministic
LangGraph `jira_ticket` node. The default `ATLASSIAN_MCP_AUTH_MODE=oauth` starts
Atlassian's browser consent flow the first time that node runs and reuses the
token on later runs. The token payload is encrypted under the user's local
application-data folder; its small Fernet key is kept in the operating-system
credential vault. It does not give Jira write tools to the LLM or store the OAuth
token in `.env`.

The OAuth request is constrained to identity/offline access and the Jira
`read`, `write`, and `search` agent-interface scopes used by this workflow.

SignalDesk pins the local OAuth redirect to
`http://localhost:8765/callback` by default. Keep
`ATLASSIAN_OAUTH_CALLBACK_PORT` stable across runs so the callback matches the
dynamically registered MCP client. The first run after upgrading creates a new,
separately namespaced encrypted OAuth cache and may request consent again. If an
Atlassian organization restricts Rovo MCP client domains, allow this localhost
callback—or the organization-approved fixed port—before running the preflight.

For unattended execution, set `ATLASSIAN_MCP_AUTH_MODE=api_token`. An organization
admin must enable API-token access; the personal token must belong to
`ATLASSIAN_MCP_EMAIL` and include `read:jira:agent-interface`,
`write:jira:agent-interface`, and `search:jira:agent-interface`. A generic or
expired Jira REST token is not sufficient. MCP transport errors are flattened in
the console so an underlying HTTP status or permission error is visible instead
of only a `TaskGroup` wrapper.

## Storage

- Supabase PostgreSQL stores durable LangGraph checkpoints through `PostgresSaver`
  using `CHECKPOINT_DATABASE_URL`; CockroachDB remains isolated to pgvector-backed
  validated incident memory through `DATABASE_URL`.
- `validated_incidents` stores 384-dimensional embeddings for reviewed incident retrieval.
- `data/agent_audit.jsonl` records a redacted append-only local audit trail.
- `sql/init.sql` documents the trusted-memory, review, and audit schema. Runtime setup creates/migrates the trusted-memory table automatically.

The built-in hashing embedder is deterministic and requires no model download. Similarity is retrieval guidance only; it is never interpreted as diagnostic confidence.

## Main modules

- `langgraph_app.py`: orchestration, selective Tree-of-Thought branches, critic, evidence gate, interrupt/resume, final admission.
- `tools/jira.py`: OAuth/API-token Atlassian MCP Jira delivery and idempotency through LangChain's MCP adapter.
- `review_delivery.py` / `review_server.py`: authenticated UI handoff into the Python LangGraph Jira node.
- `agentinstructions.json`: external agent prompts, graph feedback, and tool descriptions.
- `toolkit.py`: explicit read-only action allowlist.
- `tools/local_logs.py`: bounded local log discovery/search/context.
- `tools/operational.py`: allowlisted local source, metrics, and deployment reads.
- `validation.py`: deterministic evidence and confidence guardrails.
- `review.py`: human decision handling and trusted-memory eligibility.
- `stores/pgvector_store.py`: CockroachDB/PostgreSQL vector memory.
- `audit.py`: redacted audit events.

The Confluence interface remains available as an optional read-only MCP adapter. When it is not configured, a local stub is used; the system does not require Splunk.
