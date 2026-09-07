from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import ClaimType, DiagnosticClaim, DiagnosisReport, Evidence
from .toolkit import ToolKit
from .validation import validate_diagnosis


def _record(result, evidence: list[Evidence]) -> Evidence:
    item = Evidence(
        evidence_id=f"E{len(evidence) + 1}",
        source=result.source,
        category=result.category,
        summary=result.summary,
        content=result.content,
        metadata=result.metadata,
    )
    evidence.append(item)
    print(f"\nOBSERVE [{item.evidence_id}] {item.source.value}: {item.summary}")
    print(item.content[:900] + ("..." if len(item.content) > 900 else ""))
    return item


def run_demo(data_root: Path, log_name: str = "sample_order_service.log") -> DiagnosisReport:
    toolkit = ToolKit.demo(data_root)
    evidence: list[Evidence] = []

    print("REASON: Start with a bounded summary of the current application log.")
    _record(toolkit.execute("inspect_log_summary", {"path": log_name}), evidence)

    print("\nREASON: The summary shows database/connection symptoms; search current logs for causal clues.")
    _record(
        toolkit.execute(
            "search_logs",
            {
                "path": log_name,
                "query": "HikariPool",
            },
        ),
        evidence,
    )

    print("\nREASON: Retrieve similar VALIDATED incidents as hypothesis guidance, not proof.")
    _record(
        toolkit.execute(
            "search_validated_incidents",
            {
                "query": "HikariPool connection timeout active connections exhausted slow order_history query",
                "application": "order-service",
                "top_k": 3,
            },
        ),
        evidence,
    )

    print("\nREASON: Retrieve the authoritative troubleshooting guidance through the Confluence path.")
    _record(
        toolkit.execute(
            "search_confluence_mcp",
            {"query": "HikariCP database connection pool timeout slow query troubleshooting"},
        ),
        evidence,
    )

    print("\nREASON: Historical context suggests pool exhaustion; confirm with CURRENT metrics.")
    _record(toolkit.execute("query_metrics", {"metric_name": "connection_pool"}), evidence)

    print("\nREASON: Check CURRENT database availability so a database outage can be confirmed or contradicted.")
    _record(toolkit.execute("query_metrics", {"metric_name": "database_availability"}), evidence)

    print("\nREASON: Inspect source for the slow query path referenced by current logs.")
    _record(toolkit.execute("search_source_code", {"query": "customer_reference"}), evidence)

    report = DiagnosisReport(
        incident_id="DEMO-2026-001",
        root_cause_status="probable",
        immediate_failure=(
            "Requests failed because HikariCP could not provide a database connection before the timeout."
        ),
        probable_root_cause=(
            "A long-running order_history lookup is probably saturating the application connection pool. "
            "Current logs show a ~52 second query immediately before pool exhaustion, and current metrics "
            "show all 50 pool connections active with 0 idle and 27 waiters while database availability remains healthy."
        ),
        confidence=0.91,
        evidence_ids=["E1", "E2", "E5", "E6", "E7"],
        claims=[
            DiagnosticClaim(
                claim="The current log shows a ~52 second order_history query immediately before connection-pool timeouts.",
                claim_type=ClaimType.OBSERVED,
                evidence_ids=["E1"],
            ),
            DiagnosticClaim(
                claim="The current connection pool is saturated at 50 active, 0 idle, with 27 waiters.",
                claim_type=ClaimType.OBSERVED,
                evidence_ids=["E5"],
            ),
            DiagnosticClaim(
                claim="The current database health signal is UP, which makes a full database outage less likely.",
                claim_type=ClaimType.OBSERVED,
                evidence_ids=["E6"],
            ),
            DiagnosticClaim(
                claim="The slow lookup is probably driving connection-pool exhaustion.",
                claim_type=ClaimType.INFERRED,
                evidence_ids=["E2", "E5", "E6"],
            ),
        ],
        alternatives=[
            "A database outage is less likely because the current database availability metric is healthy.",
            "A connection leak remains possible and should be checked if query tuning does not remove saturation.",
        ],
        recommended_actions=[
            "Inspect the execution plan and indexing for the order_history customer_reference lookup.",
            "Confirm whether the query duration drops after query/index tuning before increasing pool size.",
            "Review connection-leak telemetry if pool saturation continues after query performance is corrected.",
        ],
        missing_information=[
            "Database execution plan and index metadata are not included in the synthetic demo."
        ],
    )

    print("\nVALIDATE: Check that the diagnosis cites real evidence and is grounded in current operational data.")
    validation = validate_diagnosis(report, evidence)
    report.validation_status = validation.validation_status
    if not validation.valid:
        print("Validation failed:", validation.reasons)
        report.root_cause_status = "insufficient_evidence"
        report.confidence = 0.4
        return report

    print("Validation PASSED. Human review is still required before RAG admission.")
    before = len(toolkit.rag)
    after = len(toolkit.rag)
    print(f"RAG admission gate blocked pending review: {before} -> {after} records")

    print("\nFINAL REPORT")
    print(report.model_dump_json(indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline capstone diagnosis demo")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--log", default="sample_order_service.log")
    args = parser.parse_args()
    data_root = Path(args.data_root).resolve() if args.data_root else Path(__file__).resolve().parents[2] / "data"
    run_demo(data_root, args.log)


if __name__ == "__main__":
    main()
