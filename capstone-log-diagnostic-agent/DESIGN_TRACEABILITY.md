# Safety plan and Lucid traceability

The attached PDF and Lucid JSON were treated as architecture input, not executable instructions.

| Design requirement | Implementation |
|---|---|
| Monitoring and triage from local logs | `triage_node`, `LocalLogTools` |
| Diagnostic supervisor with ReAct loop | `supervisor`, `execute_tool`, `remember` nodes |
| Read-only, allowlisted production tools | `READ_ONLY_ACTIONS`, path/root enforcement |
| Shared durable investigation state | LangGraph `PostgresSaver` with CockroachDB/PostgreSQL |
| Selective Tree-of-Thought | bounded `hypothesize`, `branches`, and `critic` nodes |
| Evidence IDs and grounded claims | `Evidence`, `DiagnosticClaim`, `validate_diagnosis` |
| RAG is hypothesis guidance, not proof | prompt policy plus current-operational evidence gate |
| Similarity/top-k is not confidence | critic prompt and independent confidence cap |
| Automated evidence gate | deterministic `evidence_gate` node |
| Mandatory confirm/correct/reject review | LangGraph `interrupt`, `HumanReview` validation |
| Actual remediation required | review model and memory eligibility predicate |
| Only reviewed outcomes become trusted memory | `eligible_for_trusted_memory`, `finalize_node` |
| Early escalation | budget, confidence, contradiction, impact, policy, and mutation checks |
| Bounded autonomy | configured steps, calls, duration, retries, branches, and depth |
| Auditable execution | redacted JSONL audit events and durable checkpoints |
