"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AppHeader } from "./app-header";
import type { DecisionValue, JiraTicket, ReviewDecisionRecord, ReviewItem } from "./types";

const decisionOptions: Array<{ value: DecisionValue; label: string; mark: string; hint: string }> = [
  { value: "approved", label: "Approved", mark: "OK", hint: "Accept the diagnosis and proposed path" },
  { value: "rejected", label: "Rejected", mark: "NO", hint: "The evidence does not support it" },
  { value: "already_addressed", label: "Already Addressed", mark: "AA", hint: "The issue has already been remediated" },
  { value: "duplicate", label: "Duplicate", mark: "DU", hint: "Link this to an existing incident" },
  { value: "inconclusive", label: "Inconclusive", mark: "?", hint: "More evidence is required" },
];

type Filter = "all" | "pending" | "decided";
type DiagnosisDraft = { decision: DecisionValue | null; comments: string };

function statusLabel(status: ReviewItem["reviewStatus"]) {
  return status === "already_addressed"
    ? "Already addressed"
    : status.charAt(0).toUpperCase() + status.slice(1);
}

function isIncidentReviewed(item: ReviewItem) {
  return item.payload.diagnoses.length > 0 && item.payload.diagnoses.every((diagnosis) =>
    (item.diagnosisDecisions ?? []).some((decision) => decision.diagnosisId === diagnosis.id)
  );
}

function incidentStatusLabel(item: ReviewItem) {
  const latest = item.diagnosisDecisions ?? [];
  const allReviewed = isIncidentReviewed(item);
  if (!allReviewed) return latest.length > 0 ? "Partially reviewed" : "Pending";
  const distinct = new Set(latest.map((decision) => decision.decision));
  return distinct.size > 1 ? "Mixed decisions" : statusLabel(item.reviewStatus);
}

function incidentStatusClass(item: ReviewItem) {
  if (!isIncidentReviewed(item)) return item.diagnosisDecisions?.length ? "partial" : "pending";
  return item.reviewStatus;
}

const confidencePercent = (value: number) => `${Math.round(value * 100)}%`;

function supportingEvidence(item: ReviewItem, evidenceIds: string[]) {
  const wanted = new Set(evidenceIds);
  return item.payload.evidence.filter((evidence) => wanted.has(evidence.id));
}

function publicScenarioBasis(value: string | undefined) {
  return value?.replace(new RegExp("\\bLang" + "Graph\\b", "gi"), "automated workflow");
}

function enrichSuggestedChanges(item: ReviewItem, fallbacks: ReviewItem[]) {
  const fallback = fallbacks.find((candidate) => candidate.incidentId === item.incidentId);
  if (!fallback) return item;
  return {
    ...item,
    payload: {
      ...item.payload,
      dataOrigin: item.payload.dataOrigin ?? fallback.payload.dataOrigin,
      sourceProject: item.payload.sourceProject ?? fallback.payload.sourceProject,
      scenarioBasis: item.payload.scenarioBasis ?? fallback.payload.scenarioBasis,
      suggestedChanges: item.payload.suggestedChanges.map((change) => ({
        ...fallback.payload.suggestedChanges.find((candidate) => candidate.id === change.id),
        ...change,
      })),
    },
  };
}

export function ReviewConsole({
  initialReviews,
  reviewerName,
  isAuthenticated,
}: {
  initialReviews: ReviewItem[];
  reviewerName: string;
  isAuthenticated: boolean;
}) {
  const [reviews, setReviews] = useState(initialReviews);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [detailIncident, setDetailIncident] = useState<ReviewItem | null>(null);
  const [reviewIncident, setReviewIncident] = useState<ReviewItem | null>(null);
  const [diagnosisDrafts, setDiagnosisDrafts] = useState<Record<string, DiagnosisDraft>>({});
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const deepLinkHandled = useRef(false);

  useEffect(() => {
    let active = true;
    const refresh = () => fetch("/api/reviews")
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not refresh the review queue");
        return (await response.json()) as { reviews: ReviewItem[] };
      })
      .then(({ reviews: loaded }) => {
        if (active) {
          setReviews(loaded.map((item) => enrichSuggestedChanges(item, initialReviews)));
        }
      })
      .catch(() => undefined);
    void refresh();
    const refreshTimer = window.setInterval(refresh, 4000);
    return () => {
      active = false;
      window.clearInterval(refreshTimer);
    };
  }, [initialReviews]);

  useEffect(() => {
    if (deepLinkHandled.current) return;
    const search = new URLSearchParams(window.location.search);
    const incidentId = search.get("incidentId");
    if (!incidentId) return;
    const incident = reviews.find((item) => item.incidentId === incidentId);
    if (!incident) return;

    deepLinkHandled.current = true;
    queueMicrotask(() => {
      setQuery(incidentId);
      if (search.get("action") === "review") {
        setReviewIncident(incident);
        setDiagnosisDrafts(Object.fromEntries(incident.payload.diagnoses.map((diagnosis) => {
          const previous = incident.diagnosisDecisions.find((saved) => saved.diagnosisId === diagnosis.id);
          return [diagnosis.id, {
            decision: previous?.decision ?? null,
            comments: previous?.comments ?? "",
          }];
        })));
      } else {
        setDetailIncident(incident);
      }
    });
  }, [reviews]);

  useEffect(() => {
    const hasModal = Boolean(detailIncident || reviewIncident);
    if (!hasModal) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDetailIncident(null);
        setReviewIncident(null);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [detailIncident, reviewIncident]);

  const visibleReviews = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return reviews.filter((item) => {
      const matchesFilter = filter === "all" ||
        (filter === "pending" && !isIncidentReviewed(item)) ||
        (filter === "decided" && isIncidentReviewed(item));
      const matchesQuery = !normalized ||
        `${item.incidentId} ${item.title} ${item.application}`.toLowerCase().includes(normalized);
      return matchesFilter && matchesQuery;
    });
  }, [reviews, filter, query]);

  const pendingCount = reviews.filter((item) => !isIncidentReviewed(item)).length;
  const decidedCount = reviews.length - pendingCount;
  const highestConfidence = reviews.length
    ? Math.max(...reviews.map((item) => item.topConfidence))
    : 0;
  const reviewIsComplete = Boolean(reviewIncident?.payload.diagnoses.every((diagnosis) => {
    const draft = diagnosisDrafts[diagnosis.id];
    return draft?.decision && draft.comments.trim();
  }));

  function openDetails(item: ReviewItem) {
    setDetailIncident(item);
  }

  function openReview(item: ReviewItem) {
    setReviewIncident(item);
    setDiagnosisDrafts(Object.fromEntries(item.payload.diagnoses.map((diagnosis) => {
      const previous = item.diagnosisDecisions.find((saved) => saved.diagnosisId === diagnosis.id);
      return [diagnosis.id, {
        decision: previous?.decision ?? null,
        comments: previous?.comments ?? "",
      }];
    })));
    setNotice(null);
  }

  function updateDiagnosisDraft(diagnosisId: string, update: Partial<DiagnosisDraft>) {
    setDiagnosisDrafts((current) => ({
      ...current,
      [diagnosisId]: { ...current[diagnosisId], ...update },
    }));
  }

  async function submitDecision() {
    if (!reviewIncident || !reviewIsComplete) return;
    const submittedDecisions = reviewIncident.payload.diagnoses.map((diagnosis) => ({
      diagnosisId: diagnosis.id,
      decision: diagnosisDrafts[diagnosis.id].decision!,
      comments: diagnosisDrafts[diagnosis.id].comments.trim(),
    }));
    setSaving(true);
    setNotice(null);
    try {
      const response = await fetch(
        `/api/reviews/${encodeURIComponent(reviewIncident.incidentId)}/decision`,
        {
          method: "POST",
          headers: { "content-type": "application/json", "x-reviewer-name": reviewerName },
          body: JSON.stringify({ decisions: submittedDecisions }),
        }
      );
      const body = (await response.json()) as {
        decisions?: ReviewDecisionRecord[];
        reviewStatus?: ReviewItem["reviewStatus"];
        jiraTickets?: JiraTicket[];
        memoryAdmission?: { status?: string; error?: string | null } | null;
        error?: string;
      };
      if (!response.ok || !body.decisions || !body.reviewStatus) {
        throw new Error(body.error || "The decision could not be saved");
      }
      const savedDecisions = body.decisions;
      const jiraTickets = body.jiraTickets ?? [];
      setReviews((current) => current.map((item) => item.incidentId === reviewIncident.incidentId
        ? {
            ...item,
            reviewStatus: body.reviewStatus!,
            latestDecision: savedDecisions[0] ?? item.latestDecision,
            diagnosisDecisions: savedDecisions,
            jiraTickets: [
              ...item.jiraTickets.filter((ticket) => !jiraTickets.some((updated) => updated.diagnosisId === ticket.diagnosisId)),
              ...jiraTickets,
            ],
          }
        : item));
      const createdKeys = jiraTickets.filter((ticket) => ticket.status === "created").map((ticket) => ticket.issueKey).filter(Boolean);
      const failedTickets = jiraTickets.filter((ticket) => ticket.status === "failed").length;
      const pendingTickets = jiraTickets.filter((ticket) => ticket.status === "pending").length;
      const memoryWarning = body.memoryAdmission?.status === "failed"
        ? ` Jira was linked, but incident-memory persistence needs retry: ${body.memoryAdmission.error ?? "unknown error"}.`
        : "";
      const jiraSummary = createdKeys.length
        ? ` Jira ${createdKeys.join(", ")} created.`
        : failedTickets
          ? ` ${failedTickets} Jira ticket${failedTickets === 1 ? "" : "s"} could not be created; the approval remains saved.`
          : pendingTickets
            ? " Jira creation is in progress."
            : "";
      setNotice(`${savedDecisions.length} diagnosis decision${savedDecisions.length === 1 ? "" : "s"} saved.${jiraSummary}${memoryWarning}`);
      setReviewIncident(null);
      setDiagnosisDrafts({});
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The decision could not be saved");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="console-shell">
      <AppHeader active="review" reviewerName={reviewerName} isAuthenticated={isAuthenticated} statusLabel="Review queue live" />

      {notice && !reviewIncident && (
        <div className="save-toast" role="status">
          <span aria-hidden="true">✓</span>
          <strong>{notice}</strong>
          <button type="button" aria-label="Dismiss notification" onClick={() => setNotice(null)}>×</button>
        </div>
      )}

      <section className="list-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Reviewer-guided operations</p>
            <h1>Incident review queue</h1>
            <p>Review agent findings, inspect the supporting context, and record a disposition.</p>
          </div>
          <div className="page-heading-note"><span>◆</span><p><strong>Audited decisions</strong>Reviewer identity, selected diagnosis, comments, and time are retained.</p></div>
        </div>

        <div className="summary-row">
          <article><span>Awaiting review</span><strong>{pendingCount}</strong><small>Needs reviewer input</small></article>
          <article><span>Decided</span><strong>{decidedCount}</strong><small>Completed dispositions</small></article>
          <article><span>Highest confidence</span><strong>{confidencePercent(highestConfidence)}</strong><small>Across open diagnoses</small></article>
        </div>

        <section className="queue-card">
          <div className="queue-toolbar">
            <div>
              <h2>Suggested incidents</h2>
              <span>{visibleReviews.length} of {reviews.length} shown</span>
            </div>
            <div className="toolbar-controls">
              <label className="search-field">
                <span>Search</span>
                <input aria-label="Search incidents" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="ID, title, or application" />
              </label>
              <div className="filter-tabs" role="tablist" aria-label="Review queue filters">
                {(["all", "pending", "decided"] as const).map((value) => (
                  <button key={value} type="button" className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>
                    {value === "all" ? "All" : value === "pending" ? "Needs review" : "Decided"}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="incident-table" role="table" aria-label="Suggested incidents">
            <div className="table-head" role="row">
              <span role="columnheader">Severity</span>
              <span role="columnheader">Incident ID</span>
              <span role="columnheader">Incident</span>
              <span role="columnheader">Application</span>
              <span role="columnheader">Diagnoses</span>
              <span role="columnheader">Confidence</span>
              <span role="columnheader">Status</span>
              <span role="columnheader">Jira</span>
              <span role="columnheader">Actions</span>
            </div>
            {visibleReviews.map((item) => {
              const linkedTickets = item.jiraTickets.filter((ticket) => ticket.status === "created" && ticket.issueUrl);
              const createdWithoutLink = item.jiraTickets.some((ticket) => ticket.status === "created" && !ticket.issueUrl);
              const hasPendingTicket = item.jiraTickets.some((ticket) => ticket.status === "pending");
              const hasFailedTicket = item.jiraTickets.some((ticket) => ticket.status === "failed");
              return <article className="table-row" role="row" key={item.incidentId}>
                <div role="cell"><span className={`severity ${item.severity.toLowerCase().replace("-", "")}`}>{item.severity}</span></div>
                <div className="incident-id-cell" role="cell"><strong>{item.incidentId}</strong>{item.payload.dataOrigin === "synthetic" && <span className="synthetic-badge">Synthetic</span>}</div>
                <div className="incident-cell" role="cell">
                  <strong>{item.title}</strong>
                  <span>{item.payload.detectedAt}</span>
                </div>
                <div className="application-cell" role="cell"><strong>{item.application}</strong><span>{item.payload.service}</span></div>
                <div className="diagnosis-count" role="cell"><strong>{item.diagnosisCount}</strong><span>candidate{item.diagnosisCount === 1 ? "" : "s"}</span></div>
                <div className="table-confidence" role="cell"><strong>{confidencePercent(item.topConfidence)}</strong><span><i style={{ width: confidencePercent(item.topConfidence) }} /></span></div>
                <div className="review-status-cell" role="cell"><span className={`status-pill status-${incidentStatusClass(item)}`}>{incidentStatusLabel(item)}</span></div>
                <div className="jira-column-cell" role="cell" aria-label="Jira delivery status">
                  {linkedTickets.map((ticket) => (
                    <a key={ticket.diagnosisId} href={ticket.issueUrl!} target="_blank" rel="noreferrer">
                      {ticket.issueKey ?? "Open ticket"} ↗
                    </a>
                  ))}
                  {createdWithoutLink && <span className="jira-created-label">Created</span>}
                  {hasPendingTicket && <span className="jira-ticket-pending">Pending</span>}
                  {hasFailedTicket && <span className="jira-ticket-failed">Failed</span>}
                  {!item.jiraTickets.length && <span className="jira-not-requested">Not requested</span>}
                </div>
                <div className="row-actions" role="cell">
                  <button type="button" className="secondary-action" onClick={() => openDetails(item)}>View details</button>
                  <button type="button" className="primary-action" onClick={() => openReview(item)}>{isIncidentReviewed(item) ? "Review again" : "Review"}</button>
                </div>
              </article>;
            })}
            {visibleReviews.length === 0 && <div className="no-results">No incidents match this view.</div>}
          </div>
        </section>
      </section>

      {detailIncident && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setDetailIncident(null)}>
          <section className="modal detail-modal" role="dialog" aria-modal="true" aria-labelledby="incident-detail-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <div className="modal-kicker"><span className={`severity ${detailIncident.severity.toLowerCase().replace("-", "")}`}>{detailIncident.severity}</span>{detailIncident.payload.dataOrigin === "synthetic" && <span className="synthetic-badge">Synthetic scenario</span>}<span>{detailIncident.incidentId}</span><span>{detailIncident.payload.detectedAt}</span></div>
                <h2 id="incident-detail-title">{detailIncident.title}</h2>
                <p>{detailIncident.symptom}</p>
              </div>
              <button type="button" className="close-button" aria-label="Close incident details" onClick={() => setDetailIncident(null)}>×</button>
            </header>

            <div className="detail-facts">
              <div><span>Service</span><strong>{detailIncident.payload.service}</strong></div>
              <div><span>Environment</span><strong>{detailIncident.environment}</strong></div>
              <div><span>Owner</span><strong>{detailIncident.payload.owner}</strong></div>
              <div><span>Impact</span><strong>{detailIncident.payload.affected}</strong></div>
            </div>

            {detailIncident.payload.dataOrigin === "synthetic" && (
              <div className="scenario-basis"><strong>Training scenario based on {detailIncident.payload.sourceProject ?? detailIncident.application}</strong><span>{publicScenarioBasis(detailIncident.payload.scenarioBasis) ?? "Modeled from the project architecture; no production event or customer data is represented."}</span></div>
            )}

            <div className="modal-scroll">
              <section className="modal-section">
                <div className="section-heading"><div><p className="eyebrow">Agent assessment</p><h3>Candidate diagnoses</h3></div><span>{detailIncident.payload.diagnoses.length} evaluated</span></div>
                <div className="diagnosis-list">
                  {detailIncident.payload.diagnoses.map((item, index) => {
                    const ticket = detailIncident.jiraTickets.find((candidate) => candidate.diagnosisId === item.id);
                    const evidence = supportingEvidence(detailIncident, item.evidenceIds);
                    return (
                      <article className="diagnosis-card" key={item.id}>
                        <div className="diagnosis-rank">{index + 1}</div>
                        <div className="diagnosis-copy">
                          <div className="diagnosis-title-row"><strong>{item.title}</strong>{index === 0 && <span className="recommended-tag">Recommended</span>}</div>
                          <p>{item.summary}</p>
                          <div className="signal-row">{item.signals.map((signal) => <span key={signal}>{signal}</span>)}</div>
                          <div className="evidence-row">{item.evidenceIds.map((id) => <span key={id}>{id}</span>)}</div>
                          <div className="diagnosis-evidence">
                            <h4>Supporting code and operational evidence</h4>
                            {evidence.length ? evidence.map((entry) => (
                              <article key={entry.id}>
                                <div><strong>{entry.id} · {entry.source}</strong><span>{entry.summary ?? "Evidence excerpt"}</span></div>
                                <pre><code>{entry.detail}</code></pre>
                              </article>
                            )) : <p>No evidence excerpt was supplied for this hypothesis.</p>}
                          </div>
                          {ticket?.status === "created" && ticket.issueUrl && (
                            <a className="jira-ticket-link" href={ticket.issueUrl} target="_blank" rel="noreferrer">Jira {ticket.issueKey} ↗</a>
                          )}
                          {ticket?.status === "pending" && <span className="jira-ticket-pending">Jira ticket pending</span>}
                          {ticket?.status === "failed" && <span className="jira-ticket-failed">Jira creation failed</span>}
                        </div>
                        <div className="confidence-block"><strong>{confidencePercent(item.confidence)}</strong><span>confidence</span></div>
                      </article>
                    );
                  })}
                </div>
              </section>

              <section className="modal-section split-section">
                <div>
                  <div className="section-heading"><div><p className="eyebrow">Remediation</p><h3>Suggested changes</h3></div></div>
                  <div className="change-list">
                    {detailIncident.payload.suggestedChanges.map((change, index) => (
                      <article className="change-card" key={change.id}>
                        <span className="change-number">0{index + 1}</span>
                        <div className="change-content">
                          <div className="change-title-row"><strong>{change.title}</strong><span>{change.category}</span><span className={`risk risk-${change.risk.toLowerCase()}`}>{change.risk} risk</span>{change.diagnosisId && <span className="diagnosis-link">For {change.diagnosisId}</span>}</div>
                          <p className="change-summary">{change.detail}</p>
                          <div className="implementation-details">
                            <h4>Implementation details</h4>
                            <p>{change.implementation ?? "No additional implementation steps were supplied by the diagnostic agent."}</p>
                            {change.files && change.files.length > 0 && (
                              <div className="affected-files"><span>Affected files</span>{change.files.map((file) => <code key={file}>{file}</code>)}</div>
                            )}
                            {change.code && (
                              <div className="code-preview">
                                <div><span>Suggested code</span><small>{change.language ?? "text"}</small></div>
                                <pre><code>{change.code}</code></pre>
                              </div>
                            )}
                            <div className="change-checks">
                              {change.validation && <div><span>Validation</span><p>{change.validation}</p></div>}
                              {change.rollback && <div><span>Rollback</span><p>{change.rollback}</p></div>}
                            </div>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="section-heading"><div><p className="eyebrow">Observed facts</p><h3>Evidence timeline</h3></div></div>
                  <div className="timeline">
                    {detailIncident.payload.evidence.map((event) => (
                      <article key={event.id}><time>{event.time}</time><span className={`timeline-dot ${event.tone}`} /><div><span>{event.id} · {event.source}</span><p>{event.detail}</p></div></article>
                    ))}
                  </div>
                </div>
              </section>

              <section className="modal-section similar-section">
                <div className="section-heading"><div><p className="eyebrow">Historical context</p><h3>Similar incidents</h3></div><span>Guidance only</span></div>
                {detailIncident.payload.similarIncidents.length ? (
                  <div className="similar-grid">
                    {detailIncident.payload.similarIncidents.map((incident) => (
                      <article key={incident.id}><div><strong>{incident.id}</strong><span>{confidencePercent(incident.similarity)} match</span></div><h4>{incident.title}</h4><p>{incident.resolution}</p><small>{incident.age}</small></article>
                    ))}
                  </div>
                ) : <p className="empty-copy">No sufficiently similar reviewed incidents were found.</p>}
              </section>
            </div>

            <footer className="modal-footer">
              <button type="button" className="secondary-action" onClick={() => setDetailIncident(null)}>Close</button>
              <button type="button" className="primary-action" onClick={() => { const item = detailIncident; setDetailIncident(null); openReview(item); }}>Review this incident</button>
            </footer>
          </section>
        </div>
      )}

      {reviewIncident && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setReviewIncident(null)}>
          <section className="modal action-modal" role="dialog" aria-modal="true" aria-labelledby="decision-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="modal-header compact">
              <div><p className="eyebrow">Reviewer decision</p><h2 id="decision-title">Review {reviewIncident.incidentId}</h2><p>{reviewIncident.title}</p></div>
              <button type="button" className="close-button" aria-label="Close decision dialog" onClick={() => setReviewIncident(null)}>×</button>
            </header>

            <div className="action-modal-body">
              <div className="per-diagnosis-intro">
                <strong>Decide on each diagnosis independently</strong>
                <p>Every candidate requires its own disposition and reviewer comment. All entries are saved as separate audit records.</p>
              </div>

              <div className="per-diagnosis-list">
                {reviewIncident.payload.diagnoses.map((item, index) => {
                  const draft = diagnosisDrafts[item.id] ?? { decision: null, comments: "" };
                  const previous = reviewIncident.diagnosisDecisions.find((saved) => saved.diagnosisId === item.id);
                  const evidence = supportingEvidence(reviewIncident, item.evidenceIds);
                  return (
                    <section className="diagnosis-review-card" key={item.id} aria-labelledby={`review-${item.id}`}>
                      <header>
                        <span className="diagnosis-rank">{index + 1}</span>
                        <div><strong id={`review-${item.id}`}>{item.title}</strong><p>{item.summary}</p></div>
                        <div className="confidence-block"><strong>{confidencePercent(item.confidence)}</strong><span>confidence</span></div>
                      </header>
                      <div className="diagnosis-evidence review-evidence">
                        <h4>Evidence to verify before deciding</h4>
                        {evidence.length ? evidence.map((entry) => (
                          <article key={entry.id}>
                            <div><strong>{entry.id} · {entry.source}</strong><span>{entry.summary ?? "Evidence excerpt"}</span></div>
                            <pre><code>{entry.detail}</code></pre>
                          </article>
                        )) : <p>No evidence excerpt was supplied for this hypothesis.</p>}
                      </div>
                      {previous && (
                        <div className="diagnosis-history"><span>Previous: {statusLabel(previous.decision)}</span><small>{previous.reviewerName} · {previous.comments}</small></div>
                      )}
                      <fieldset className="decision-picker">
                        <legend>Decision for {item.id}</legend>
                        <div className="decision-options">
                          {decisionOptions.map((option) => (
                            <button type="button" role="radio" aria-label={`${option.label} for ${item.title}`} aria-checked={draft.decision === option.value} key={option.value} className={draft.decision === option.value ? `selected decision-${option.value}` : ""} onClick={() => updateDiagnosisDraft(item.id, { decision: option.value })}>
                              <span>{option.mark}</span><div><strong>{option.label}</strong><small>{option.hint}</small></div>
                            </button>
                          ))}
                        </div>
                      </fieldset>
                      <label className="comment-field">
                        <span>Comments for {item.id} <b>Required</b></span>
                        <textarea autoFocus={index === 0} maxLength={1000} value={draft.comments} onChange={(event) => updateDiagnosisDraft(item.id, { comments: event.target.value })} placeholder="Explain the evidence for this diagnosis decision..." rows={3} />
                        <small>{draft.comments.length}/1000</small>
                      </label>
                    </section>
                  );
                })}
              </div>
              {notice && <div className="save-notice" role="status">{notice}</div>}
            </div>

            <footer className="modal-footer action-footer">
              <p><span>◆</span> Saving as {reviewerName}</p>
              <div><button type="button" className="secondary-action" onClick={() => setReviewIncident(null)}>Cancel</button><button type="button" className="primary-action submit-action" disabled={!reviewIsComplete || saving} onClick={submitDecision}>{saving ? "Saving..." : `Submit ${reviewIncident.payload.diagnoses.length} decision${reviewIncident.payload.diagnoses.length === 1 ? "" : "s"}`}</button></div>
            </footer>
          </section>
        </div>
      )}
    </main>
  );
}
