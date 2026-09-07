from __future__ import annotations

import json
from pathlib import Path

from ..models import EvidenceCategory, EvidenceSource, ToolResult
from ..redaction import redact


SOURCE_SUFFIXES = {
    ".py", ".java", ".kt", ".js", ".jsx", ".ts", ".tsx", ".cs",
    ".xml", ".yml", ".yaml", ".properties", ".toml", ".sql", ".md",
}
SKIPPED_DIRECTORIES = {
    ".git", ".idea", ".vscode", "node_modules", "venv", ".venv",
    "target", "dist", "build", "__pycache__", ".pytest_cache",
}


class OperationalTools:
    """Read-only source, metrics, and change tools constrained to explicit roots."""

    def __init__(
        self,
        project_roots: dict[str, Path],
        log_root: Path,
        max_source_bytes: int = 1024 * 1024,
    ):
        self.project_roots = {name: root.resolve() for name, root in project_roots.items()}
        self.log_root = log_root.resolve()
        self.max_source_bytes = max_source_bytes

    def _selected_projects(self, application: str | None) -> dict[str, Path]:
        if not application:
            return self.project_roots
        matches = {
            name: root
            for name, root in self.project_roots.items()
            if name.casefold() == application.casefold()
        }
        if not matches:
            raise ValueError(
                f"Unknown application {application!r}; allowed={sorted(self.project_roots)}"
            )
        return matches

    @staticmethod
    def _is_allowed_source(path: Path) -> bool:
        return path.suffix.lower() in SOURCE_SUFFIXES and not any(
            part in SKIPPED_DIRECTORIES for part in path.parts
        )

    def list_projects(self) -> ToolResult:
        payload = [
            {"application": name, "root": str(root), "exists": root.is_dir()}
            for name, root in self.project_roots.items()
        ]
        return ToolResult(
            source=EvidenceSource.SOURCE_CODE,
            category=EvidenceCategory.OPERATIONAL,
            summary=f"Listed {len(payload)} allowlisted local source projects",
            content=json.dumps(payload, indent=2),
            metadata={"project_count": len(payload)},
            substantive=any(item["exists"] for item in payload),
        )

    def search_source_code(
        self, query: str, application: str | None = None, max_matches: int = 25
    ) -> ToolResult:
        if not query or len(query) > 200:
            raise ValueError("Source search query must contain 1-200 characters")
        max_matches = max(1, min(int(max_matches), 50))
        needle = query.casefold()
        hits: list[str] = []
        searched: list[str] = []
        for name, root in self._selected_projects(application).items():
            if not root.is_dir():
                continue
            searched.append(name)
            for path in sorted(root.rglob("*")):
                if len(hits) >= max_matches:
                    break
                if not path.is_file() or not self._is_allowed_source(path):
                    continue
                try:
                    resolved = path.resolve()
                    resolved.relative_to(root)
                except (OSError, ValueError):
                    continue
                if resolved.stat().st_size > self.max_source_bytes:
                    continue
                try:
                    lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for index, line in enumerate(lines, start=1):
                    if needle in line.casefold():
                        relative = path.relative_to(root)
                        hits.append(f"{name}/{relative}:{index}: {redact(line.strip())}")
                        if len(hits) >= max_matches:
                            break
        return ToolResult(
            source=EvidenceSource.SOURCE_CODE,
            category=EvidenceCategory.OPERATIONAL,
            summary=f"Source search for {query!r} returned {len(hits)} hits",
            content="\n".join(hits) if hits else "No source-code matches",
            metadata={"query": query, "applications": searched, "match_count": len(hits)},
            substantive=bool(hits),
        )

    def query_metrics(self, metric_name: str) -> ToolResult:
        if not metric_name or len(metric_name) > 120:
            raise ValueError("Metric name must contain 1-120 characters")
        selected: dict[str, object] = {}
        needle = metric_name.casefold()
        for path in self.log_root.rglob("*.json"):
            if "metric" not in path.name.casefold() or path.stat().st_size > self.max_source_bytes:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            serialized = json.dumps(payload, default=str)
            if needle in path.name.casefold() or needle in serialized.casefold():
                selected[str(path.relative_to(self.log_root))] = payload
        return ToolResult(
            source=EvidenceSource.METRICS,
            category=EvidenceCategory.OPERATIONAL,
            summary=f"Found {len(selected)} local metric snapshots matching {metric_name!r}",
            content=redact(json.dumps(selected, indent=2, default=str)) if selected else "No matches",
            metadata={"metric_name": metric_name, "file_count": len(selected)},
            substantive=bool(selected),
        )

    def recent_deployments(self, application: str) -> ToolResult:
        matches: list[dict[str, object]] = []
        needles = ("deploy", "release", "change")
        for path in self.log_root.rglob("*.json"):
            if not any(needle in path.name.casefold() for needle in needles):
                continue
            if path.stat().st_size > self.max_source_bytes:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if application.casefold() in json.dumps(payload, default=str).casefold():
                matches.append({"path": str(path.relative_to(self.log_root)), "data": payload})
        return ToolResult(
            source=EvidenceSource.DEPLOYMENT,
            category=EvidenceCategory.OPERATIONAL,
            summary=f"Found {len(matches)} local deployment/change records for {application}",
            content=redact(json.dumps(matches[:20], indent=2, default=str)) if matches else "No matches",
            metadata={"application": application, "record_count": len(matches)},
            substantive=bool(matches),
        )
