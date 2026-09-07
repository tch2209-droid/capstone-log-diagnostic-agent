from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .models import EvidenceCategory, EvidenceSource, ToolResult
from .stores.base import IncidentRAGStore
from .stores.in_memory_rag import InMemoryIncidentRAG
from .tools.confluence import AtlassianRovoMCPProvider, ConfluenceProvider, StubConfluenceProvider
from .tools.local_logs import LocalLogTools
from .tools.operational import OperationalTools


READ_ONLY_ACTIONS = {
    "list_logs",
    "inspect_log_summary",
    "search_logs",
    "get_log_context",
    "parse_stack_trace",
    "list_projects",
    "query_metrics",
    "get_recent_changes",
    "search_source_code",
    "search_confluence_mcp",
    "search_validated_incidents",
}


def incident_rag_from_settings(settings: Settings) -> IncidentRAGStore:
    """Create the configured long-term incident-memory store."""
    from .embeddings import HashingEmbedder

    if settings.use_pgvector:
        if not settings.database_url:
            raise RuntimeError("USE_PGVECTOR=true requires DATABASE_URL")
        from .stores.pgvector_store import PgVectorIncidentStore

        # The dependency-free hashing embedder avoids downloading a model and
        # provides deterministic 384-dimensional retrieval.
        return PgVectorIncidentStore(settings.database_url, HashingEmbedder(384))

    data_root = Path(__file__).resolve().parents[2] / "data"
    return InMemoryIncidentRAG.from_json(
        data_root / "validated_incidents.json", embedder=HashingEmbedder(384)
    )


@dataclass
class ToolKit:
    logs: LocalLogTools
    operational: OperationalTools
    confluence: ConfluenceProvider
    rag: IncidentRAGStore

    @classmethod
    def demo(cls, data_root: Path) -> "ToolKit":
        from .embeddings import HashingEmbedder

        data_root = data_root.resolve()
        return cls(
            logs=LocalLogTools(data_root),
            operational=OperationalTools({"demo": data_root / "source"}, data_root),
            confluence=StubConfluenceProvider(data_root),
            rag=InMemoryIncidentRAG.from_json(
                data_root / "validated_incidents.json", embedder=HashingEmbedder(384)
            ),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "ToolKit":
        confluence: ConfluenceProvider
        if settings.atlassian_mcp_url and settings.atlassian_cloud_id:
            confluence = AtlassianRovoMCPProvider(
                settings.atlassian_mcp_url,
                settings.atlassian_cloud_id,
                settings.atlassian_search_tool,
                settings.atlassian_mcp_email,
                settings.atlassian_mcp_api_token,
            )
        else:
            stub_root = Path(__file__).resolve().parents[2] / "data"
            confluence = StubConfluenceProvider(stub_root)

        return cls(
            logs=LocalLogTools(settings.log_root, settings.max_log_bytes),
            operational=OperationalTools(
                settings.project_roots, settings.log_root, settings.max_source_bytes
            ),
            confluence=confluence,
            rag=incident_rag_from_settings(settings),
        )

    def search_validated_incidents(
        self, query: str, application: str | None = None, top_k: int = 3
    ) -> ToolResult:
        top_k = max(1, min(int(top_k), 3))
        results = self.rag.search(query, top_k=top_k, application=application)
        payload = [item.model_dump(mode="json") for item in results]
        return ToolResult(
            source=EvidenceSource.VALIDATED_INCIDENT,
            category=EvidenceCategory.HISTORICAL,
            summary=f"Retrieved {len(results)} reviewer-validated similar incidents",
            content=json.dumps(payload, indent=2),
            metadata={"query": query, "top_k": top_k, "application": application},
            substantive=bool(results),
        )

    def execute(self, action: str, args: dict[str, Any]) -> ToolResult:
        if action not in READ_ONLY_ACTIONS:
            raise PermissionError(f"Action is not on the read-only allowlist: {action}")
        registry = {
            "list_logs": lambda: self.logs.list_logs(
                args.get("application"), int(args.get("limit", 50))
            ),
            "inspect_log_summary": lambda: self.logs.inspect_summary(args["path"]),
            "search_logs": lambda: self.logs.search(
                args["path"], args["query"], int(args.get("max_matches", 20))
            ),
            "get_log_context": lambda: self.logs.context(
                args["path"], int(args["line_number"]), int(args.get("before", 4)),
                int(args.get("after", 6)),
            ),
            "parse_stack_trace": lambda: self.logs.parse_stack_trace(args["text"]),
            "list_projects": self.operational.list_projects,
            "query_metrics": lambda: self.operational.query_metrics(args["metric_name"]),
            "get_recent_changes": lambda: self.operational.recent_deployments(args["application"]),
            "search_source_code": lambda: self.operational.search_source_code(
                args["query"], args.get("application"), int(args.get("max_matches", 25))
            ),
            "search_confluence_mcp": lambda: self.confluence.search(args["query"]),
            "search_validated_incidents": lambda: self.search_validated_incidents(
                args["query"], args.get("application"), int(args.get("top_k", 3))
            ),
        }
        return registry[action]()
