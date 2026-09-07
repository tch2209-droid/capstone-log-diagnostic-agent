"use client";

import { useEffect, useMemo, useState } from "react";

type NodeId =
  | "triage"
  | "supervisor"
  | "execute_tool"
  | "remember"
  | "draft"
  | "hypothesize"
  | "branches"
  | "critic"
  | "evidence_gate"
  | "human_review"
  | "jira_ticket"
  | "finalize";

type DemoEvent = {
  node: NodeId;
  phase: string;
  title: string;
  detail: string;
  log: string;
  evidence: number;
  confidence: number | null;
  budget: string;
  status?: "pending" | "created" | "failed";
  issueKey?: string | null;
  issueUrl?: string | null;
  createdAt?: string;
  facts?: Array<{ label: string; value: string }>;
};

type LiveRun = {
  runId: string;
  incidentId: string;
  application: string;
  status: "running" | "waiting" | "completed" | "failed";
  currentNode: NodeId | null;
  startedAt: string;
  error: string | null;
};

type LiveEvent = {
  eventId: string;
  sequence: number;
  eventType: string;
  node: NodeId | null;
  status: string;
  message: string;
  details: {
    evidenceCount?: number;
    confidence?: number | null;
    stepCount?: number;
    toolCallCount?: number;
    jiraStatus?: string | null;
    issueKey?: string | null;
    issueUrl?: string | null;
    activityTitle?: string;
    activityBody?: string;
    activityFacts?: Array<{ label: string; value: string }>;
  };
  createdAt: string;
};

const graphNodes: Array<{
  id: NodeId;
  label: string;
  role: string;
  kind: "investigate" | "reason" | "govern" | "deliver";
}> = [
  { id: "triage", label: "Triage", role: "Frame incident", kind: "investigate" },
  { id: "supervisor", label: "Supervisor", role: "Choose next action", kind: "investigate" },
  { id: "execute_tool", label: "Execute tool", role: "Read-only evidence", kind: "investigate" },
  { id: "remember", label: "Remember", role: "Update evidence ledger", kind: "investigate" },
  { id: "draft", label: "Draft", role: "Structure findings", kind: "reason" },
  { id: "hypothesize", label: "Hypothesize", role: "Create H1–H3", kind: "reason" },
  { id: "branches", label: "Branches", role: "Test alternatives", kind: "reason" },
  { id: "critic", label: "Critic", role: "Find contradictions", kind: "reason" },
  { id: "evidence_gate", label: "Evidence gate", role: "Deterministic checks", kind: "govern" },
  { id: "human_review", label: "Human review", role: "Authorize outcome", kind: "govern" },
  { id: "jira_ticket", label: "Jira ticket", role: "Idempotent delivery", kind: "deliver" },
  { id: "finalize", label: "Finalize", role: "Admit trusted memory", kind: "deliver" },
];

const demoEvents: DemoEvent[] = [
  {
    node: "triage",
    phase: "01 · Investigate",
    title: "The incident enters a bounded workflow",
    detail: "SignalDesk frames INC-PnCAgentInfo-007, records its application and severity, and initializes hard execution budgets before the model can act.",
    log: "triage · SEV-2 incident accepted for PropertyCasualtyInsuranceAgentInfo",
    evidence: 0,
    confidence: null,
    budget: "1 / 12 steps",
  },
  {
    node: "supervisor",
    phase: "01 · Investigate",
    title: "The supervisor asks for one useful observation",
    detail: "The agent selects exactly one allowlisted, read-only action. It cannot mutate production or call Jira from the investigation loop.",
    log: "supervisor · next action: inspect_log_summary",
    evidence: 0,
    confidence: null,
    budget: "2 / 12 steps",
  },
  {
    node: "execute_tool",
    phase: "01 · Investigate",
    title: "A bounded tool inspects current logs",
    detail: "Path controls, byte limits, literal search, and secret redaction constrain the evidence returned to the graph.",
    log: "execute_tool · inspect_log_summary completed within configured limits",
    evidence: 0,
    confidence: null,
    budget: "1 / 10 tools",
  },
  {
    node: "remember",
    phase: "01 · Investigate",
    title: "Operational evidence becomes traceable state",
    detail: "The normalized observation is assigned an evidence ID so every later claim can point back to its source.",
    log: "remember · E1 added: timeout pattern in current application log",
    evidence: 1,
    confidence: null,
    budget: "3 / 12 steps",
  },
  {
    node: "supervisor",
    phase: "01 · Investigate",
    title: "The evidence loop continues deliberately",
    detail: "One log pattern is useful but not enough for a probable diagnosis. The supervisor asks for a different current source type.",
    log: "supervisor · evidence diversity insufficient; next action: search_source_code",
    evidence: 1,
    confidence: null,
    budget: "4 / 12 steps",
  },
  {
    node: "execute_tool",
    phase: "01 · Investigate",
    title: "The agent inspects allowlisted source code",
    detail: "Source access is confined to configured project roots and capped by a separate output budget.",
    log: "execute_tool · search_source_code found retry configuration path",
    evidence: 1,
    confidence: null,
    budget: "2 / 10 tools",
  },
  {
    node: "remember",
    phase: "01 · Investigate",
    title: "A second source strengthens the evidence base",
    detail: "Current source evidence is stored separately from logs, satisfying the diversity needed for stronger validation later.",
    log: "remember · E2 added: source configuration corroborates timeout behavior",
    evidence: 2,
    confidence: null,
    budget: "5 / 12 steps",
  },
  {
    node: "supervisor",
    phase: "01 · Investigate",
    title: "The supervisor decides the draft is now warranted",
    detail: "The graph leaves the evidence cycle because it has enough current, substantive context—not because it reached an arbitrary confidence target.",
    log: "supervisor · proceed to structured diagnostic draft",
    evidence: 2,
    confidence: null,
    budget: "6 / 12 steps",
  },
  {
    node: "draft",
    phase: "02 · Reason",
    title: "Findings are converted into a typed report",
    detail: "Observed facts, inferences, unknowns, evidence IDs, alternatives, actions, and confidence are separated in a schema-valid diagnostic draft.",
    log: "draft · claims typed and evidence references resolved",
    evidence: 2,
    confidence: 0.82,
    budget: "7 / 12 steps",
  },
  {
    node: "hypothesize",
    phase: "02 · Reason",
    title: "The graph resists first-answer bias",
    detail: "Up to three explanations are formed. H1 is plausible, but H2 and H3 remain visible as alternatives until independently tested.",
    log: "hypothesize · H1, H2, and H3 queued for evaluation",
    evidence: 2,
    confidence: 0.82,
    budget: "3 hypotheses",
  },
  {
    node: "branches",
    phase: "02 · Reason",
    title: "Candidate diagnoses are tested independently",
    detail: "Each branch examines supporting evidence, contradictions, missing information, and safe next actions within a depth limit.",
    log: "branches · independent evaluations complete at depth ≤ 3",
    evidence: 2,
    confidence: 0.86,
    budget: "3 / 3 branches",
  },
  {
    node: "critic",
    phase: "02 · Reason",
    title: "The critic makes disagreement visible",
    detail: "The critic compares branch strength and unresolved contradictions. H1 converges as the leading explanation without erasing the alternatives.",
    log: "critic · H1 selected; no material contradiction remains",
    evidence: 2,
    confidence: 0.89,
    budget: "8 / 12 steps",
  },
  {
    node: "evidence_gate",
    phase: "03 · Verify",
    title: "Deterministic rules—not confidence—validate the draft",
    detail: "The gate verifies every citation and requires two substantive current operational sources of different types before probable findings can advance.",
    log: "evidence_gate · passed: E1 log + E2 source; citations valid",
    evidence: 2,
    confidence: 0.89,
    budget: "Gate passed",
  },
  {
    node: "human_review",
    phase: "04 · Authorize",
    title: "The workflow pauses for accountable authority",
    detail: "A reviewer inspects H1, the evidence, and remediation; then records an approved disposition and comment. The decision is durably saved first.",
    log: "human_review · H1 approved by verified reviewer; checkpoint resumed",
    evidence: 2,
    confidence: 0.89,
    budget: "Decision saved",
  },
  {
    node: "jira_ticket",
    phase: "05 · Deliver",
    title: "Jira delivery begins in Pending",
    detail: "The backend searches by a stable idempotency label. While the terminal outcome is unknown, the UI truthfully remains Pending instead of guessing failure.",
    log: "jira_ticket · pending: searching Jira for signaldesk-INC-PnCAgentInfo-007-H1",
    evidence: 2,
    confidence: 0.89,
    budget: "Side effect isolated",
    status: "pending",
  },
  {
    node: "jira_ticket",
    phase: "05 · Deliver",
    title: "The terminal result exposes a real work item",
    detail: "Jira returns issue SCRUM-6. SignalDesk persists the issue key and URL so the queue and incident details can both show a direct link.",
    log: "jira_ticket · created: SCRUM-6 · issue_id 10005",
    evidence: 2,
    confidence: 0.89,
    budget: "Created",
    status: "created",
  },
  {
    node: "finalize",
    phase: "06 · Learn",
    title: "Only an earned outcome becomes trusted memory",
    detail: "The validated, approved, remediated diagnosis with successful Jira delivery is admitted for future similarity retrieval and the run ends.",
    log: "finalize · trusted incident memory admitted; workflow complete",
    evidence: 2,
    confidence: 0.89,
    budget: "Complete",
    status: "created",
  },
];

const links: Array<{ from: NodeId; to: NodeId; className: string; label?: string }> = [
  { from: "triage", to: "supervisor", className: "link-triage-supervisor" },
  { from: "supervisor", to: "draft", className: "link-supervisor-draft", label: "enough evidence" },
  { from: "supervisor", to: "execute_tool", className: "link-supervisor-tool", label: "need evidence" },
  { from: "execute_tool", to: "remember", className: "link-tool-remember" },
  { from: "remember", to: "supervisor", className: "link-remember-supervisor", label: "loop" },
  { from: "draft", to: "hypothesize", className: "link-draft-hypothesize" },
  { from: "hypothesize", to: "branches", className: "link-hypothesize-branches" },
  { from: "branches", to: "critic", className: "link-branches-critic" },
  { from: "critic", to: "evidence_gate", className: "link-critic-gate" },
  { from: "evidence_gate", to: "human_review", className: "link-gate-human" },
  { from: "human_review", to: "jira_ticket", className: "link-human-jira" },
  { from: "jira_ticket", to: "finalize", className: "link-jira-finalize" },
];

const nodeIndex = Object.fromEntries(graphNodes.map((node) => [node.id, node]));

const phaseByNode: Record<NodeId, string> = {
  triage: "01 · Investigate",
  supervisor: "01 · Investigate",
  execute_tool: "01 · Investigate",
  remember: "01 · Investigate",
  draft: "02 · Reason",
  hypothesize: "02 · Reason",
  branches: "02 · Reason",
  critic: "02 · Reason",
  evidence_gate: "03 · Verify",
  human_review: "04 · Authorize",
  jira_ticket: "05 · Deliver",
  finalize: "06 · Learn",
};

const detailByNode: Record<NodeId, string> = {
  triage: "The live agent is framing this incident and capturing its first operational signal.",
  supervisor: "The supervisor is reasoning over current evidence and choosing one bounded next action.",
  execute_tool: "An allowlisted read-only tool is gathering evidence within configured path and output limits.",
  remember: "The latest observation is being normalized into the auditable evidence ledger.",
  draft: "Grounded findings are being separated into facts, inferences, unknowns, actions, and citations.",
  hypothesize: "Alternative explanations are being formed so the first plausible answer is not accepted automatically.",
  branches: "Candidate diagnoses are being evaluated independently against support, contradictions, and missing data.",
  critic: "The critic is comparing branch strength and surfacing unresolved disagreement.",
  evidence_gate: "Deterministic controls are validating citations, evidence quality, and source diversity.",
  human_review: "The checkpoint is waiting for an attributable reviewer decision before any delivery action.",
  jira_ticket: "The approved diagnosis is being delivered to Jira with an idempotent lookup before creation.",
  finalize: "The final report and trusted-memory admission decision are being recorded.",
};

function elapsed(startedAt: string | undefined, createdAt: string | undefined, fallback: number) {
  if (!startedAt || !createdAt) return `+${String(fallback).padStart(2, "0")}s`;
  const seconds = Math.max(0, Math.round((Date.parse(createdAt) - Date.parse(startedAt)) / 1000));
  return `+${String(seconds).padStart(2, "0")}s`;
}

export function OrchestrationDemo() {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [mode, setMode] = useState<"guided" | "live">("guided");
  const [liveRun, setLiveRun] = useState<LiveRun | null>(null);
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const guidedCurrent = demoEvents[step];
  const atEnd = step === demoEvents.length - 1;

  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get("runId");
    if (!runId) return;
    let cancelled = false;
    let connected = false;
    async function refresh() {
      try {
        const response = await fetch(`/api/orchestration?runId=${encodeURIComponent(runId!)}`, { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json() as { run: LiveRun | null; events: LiveEvent[] };
        if (!cancelled && payload.run) {
          if (!connected) {
            setMode("live");
            connected = true;
          }
          setLiveRun(payload.run);
          setLiveEvents(payload.events);
        }
      } catch {
        // Preserve the visible graph while a local UI server reconnects.
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 700);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!playing || atEnd || mode === "live") return;
    const nextStep = step + 1;
    const timer = window.setTimeout(() => {
      setStep(nextStep);
      if (nextStep === demoEvents.length - 1) setPlaying(false);
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [atEnd, mode, playing, step]);

  const liveNodeEvents = useMemo(
    () => liveEvents.filter((event): event is LiveEvent & { node: NodeId } => Boolean(event.node && nodeIndex[event.node])),
    [liveEvents],
  );
  const mappedLiveEvents: DemoEvent[] = liveNodeEvents.map((event) => ({
    node: event.node,
    phase: phaseByNode[event.node],
    title: event.details.activityTitle ?? event.message,
    detail: liveRun?.status === "failed" && liveRun.error
      ? liveRun.error
      : event.details.activityBody ?? detailByNode[event.node],
    log: `${event.node} · ${event.eventType.replaceAll("_", " ")}`,
    evidence: event.details.evidenceCount ?? 0,
    confidence: event.details.confidence ?? null,
    budget: `${event.details.stepCount ?? 0} steps · ${event.details.toolCallCount ?? 0} tools`,
    status: event.details.jiraStatus === "created" || event.details.jiraStatus === "existing"
      ? "created"
      : event.details.jiraStatus === "failed" ? "failed" : event.node === "jira_ticket" ? "pending" : undefined,
    issueKey: event.details.issueKey,
    issueUrl: event.details.issueUrl,
    createdAt: event.createdAt,
    facts: event.details.activityFacts,
  }));
  const isLive = mode === "live" && Boolean(liveRun);
  const current = isLive && mappedLiveEvents.length ? mappedLiveEvents.at(-1)! : guidedCurrent;
  const visibleEvents = isLive ? mappedLiveEvents : demoEvents.slice(0, step + 1);
  const visitedNodes = useMemo(() => {
    if (!isLive) return new Set(demoEvents.slice(0, step + 1).map((event) => event.node));
    return new Set(liveNodeEvents.filter((event) => event.eventType === "node_completed").map((event) => event.node));
  }, [isLive, liveNodeEvents, step]);
  const trace = visibleEvents.slice(-6);
  const progress = isLive
    ? Math.max(3, (visitedNodes.size / graphNodes.length) * 100)
    : ((step + 1) / demoEvents.length) * 100;

  function jumpToNode(node: NodeId) {
    if (isLive) return;
    const firstEvent = demoEvents.findIndex((event) => event.node === node);
    if (firstEvent < 0) return;
    setPlaying(false);
    setStep(firstEvent);
  }

  function restart() {
    setStep(0);
    setPlaying(true);
  }

  return (
    <section className="orchestration-page">
      <header className="orchestration-hero">
        <div>
          <p className="eyebrow">LangGraph orchestration · Capstone demo</p>
          <h1>Watch one incident become an accountable action.</h1>
          <p>{isLive ? <>Live execution for <strong>{liveRun!.incidentId}</strong> in <strong>{liveRun!.application}</strong>.</> : <>A guided replay of the implemented graph for <strong>INC-PnCAgentInfo-007</strong>, from bounded investigation to verified Jira issue <strong>SCRUM-6</strong>.</>}</p>
        </div>
        <div className="demo-disclosure">
          <span>{isLive ? "Live agent run" : "Guided replay"}</span>
          <p>{isLive ? "Connected to the running workflow. Events update automatically as each node executes." : "Representative orchestration using a verified capstone outcome. It does not start a new incident."}</p>
        </div>
      </header>

      <section className="orchestration-card" aria-label="Interactive LangGraph orchestration replay">
        <div className="demo-toolbar">
          <div className="demo-progress-copy">
            <span className="demo-status-dot" />
            <div><strong>{isLive ? liveRun!.status === "waiting" ? "Waiting for review" : liveRun!.status === "completed" ? "Run complete" : liveRun!.status === "failed" ? "Run failed" : "Live run connected" : playing ? "Replay running" : atEnd ? "Replay complete" : "Replay paused"}</strong><span>{isLive ? `${liveEvents.length} live events · 1-second demo pacing` : `Step ${String(step + 1).padStart(2, "0")} of ${demoEvents.length}`}</span></div>
          </div>
          <div className="demo-controls" aria-label="Replay controls">
            {isLive ? <button type="button" className="demo-play-button" onClick={() => { setMode("guided"); setPlaying(false); }}>View guided replay</button> : <>
              <button type="button" className="demo-icon-button" onClick={() => { setPlaying(false); setStep((value) => Math.max(0, value - 1)); }} disabled={step === 0} aria-label="Previous step">←</button>
              <button type="button" className="demo-play-button" onClick={() => liveRun ? setMode("live") : atEnd ? restart() : setPlaying((value) => !value)}>{liveRun ? "Return to live run" : atEnd ? "Replay demo" : playing ? "Pause" : "Play walkthrough"}</button>
              <button type="button" className="demo-icon-button" onClick={() => { setPlaying(false); setStep((value) => Math.min(demoEvents.length - 1, value + 1)); }} disabled={atEnd} aria-label="Next step">→</button>
            </>}
          </div>
        </div>
        <div className="demo-progress-track" aria-hidden="true"><span style={{ width: `${progress}%` }} /></div>

        <div className="graph-key" aria-label="Graph node categories">
          <span><i className="key-investigate" />Investigate</span>
          <span><i className="key-reason" />Reason</span>
          <span><i className="key-govern" />Verify and authorize</span>
          <span><i className="key-deliver" />Deliver and learn</span>
        </div>

        <div className="orchestration-graph" role="img" aria-label={`LangGraph workflow. Current node: ${nodeIndex[current.node].label}. ${current.title}`}>
          <div className="graph-lane-label lane-reasoning">Agent reasoning</div>
          <div className="graph-lane-label lane-evidence">Bounded evidence loop</div>
          <div className="graph-lane-label lane-governance">Governed action</div>

          {links.map((link) => {
            const isActive = current.node === link.to;
            const isComplete = visitedNodes.has(link.from) && visitedNodes.has(link.to);
            return (
              <span
                key={`${link.from}-${link.to}`}
                className={`graph-link ${link.className}${isActive ? " active" : isComplete ? " complete" : ""}`}
                aria-hidden="true"
              >
                {link.label && <small>{link.label}</small>}
              </span>
            );
          })}

          {graphNodes.map((node) => {
            const state = current.node === node.id ? "active" : visitedNodes.has(node.id) ? "complete" : "waiting";
            return (
              <button
                type="button"
                key={node.id}
                className={`graph-node node-${node.id} kind-${node.kind} ${state}`}
                aria-pressed={current.node === node.id}
                onClick={() => jumpToNode(node.id)}
              >
                <span className="node-state" aria-hidden="true">{state === "complete" ? "✓" : state === "active" ? "●" : ""}</span>
                <strong>{node.label}</strong>
                <small>{node.role}</small>
              </button>
            );
          })}

          {isLive && (
            <aside className="node-live-popup" key={current.createdAt} role="status" aria-live="polite">
              <span className="node-live-kicker"><i />{nodeIndex[current.node].label} · Live activity</span>
              <strong>{current.title}</strong>
              <span className="node-live-body">{current.detail}</span>
              {current.facts?.length ? <span className="node-live-facts">
                {current.facts.slice(0, 2).map((fact) => <span key={fact.label}><b>{fact.label}</b>{fact.value}</span>)}
              </span> : null}
            </aside>
          )}
        </div>

        <div className="orchestration-detail-grid">
          <article className="current-event-card" aria-live="polite">
            <div className="current-event-heading">
              <div><p>{current.phase}</p><h2>{current.title}</h2></div>
              {current.status === "pending" && <span className="demo-jira-status pending">Jira · Pending</span>}
              {current.status === "created" && <a className="demo-jira-status created" href={current.issueUrl ?? "https://agentic-dev-tacme.atlassian.net/browse/SCRUM-6"} target="_blank" rel="noreferrer">{current.issueKey ?? "SCRUM-6"} ↗</a>}
              {current.status === "failed" && <span className="demo-jira-status pending">Jira · Failed</span>}
            </div>
            <p className="current-event-detail">{current.detail}</p>
            <div className="event-metrics">
              <div><span>Active node</span><strong>{nodeIndex[current.node].label}</strong></div>
              <div><span>Evidence</span><strong>{current.evidence} item{current.evidence === 1 ? "" : "s"}</strong></div>
              <div><span>Confidence</span><strong>{current.confidence === null ? "Not scored" : `${Math.round(current.confidence * 100)}%`}</strong></div>
              <div><span>Control</span><strong>{current.budget}</strong></div>
            </div>
          </article>

          <aside className="execution-trace" aria-label="Execution trace">
            <div className="trace-heading"><div><span className="trace-live-dot" /><strong>Execution trace</strong></div><small>Original console logging remains unchanged</small></div>
            <ol>
              {trace.map((event, index) => {
                const absoluteIndex = visibleEvents.length - trace.length + index;
                return (
                  <li key={`${absoluteIndex}-${event.node}-${event.createdAt ?? "guided"}`} className={index === trace.length - 1 ? "current" : ""}>
                    <time>{elapsed(liveRun?.startedAt, event.createdAt, absoluteIndex)}</time>
                    <code>{event.log}</code>
                  </li>
                );
              })}
            </ol>
          </aside>
        </div>
      </section>

      <section className="control-model" aria-labelledby="control-model-title">
        <div><p className="eyebrow">Control model</p><h2 id="control-model-title">Useful autonomy. Explicit authority.</h2></div>
        <ol>
          <li><span>01</span><div><strong>Agent investigates</strong><p>One bounded, read-only action at a time.</p></div></li>
          <li><span>02</span><div><strong>Code verifies</strong><p>Evidence, citations, diversity, and contradictions.</p></div></li>
          <li><span>03</span><div><strong>Human authorizes</strong><p>An attributable decision resumes the checkpoint.</p></div></li>
          <li><span>04</span><div><strong>Service delivers</strong><p>Idempotent Jira creation and trusted memory.</p></div></li>
        </ol>
      </section>
    </section>
  );
}
