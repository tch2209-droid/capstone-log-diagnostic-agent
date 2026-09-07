from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from ..models import EvidenceCategory, EvidenceSource, ToolResult
from ..redaction import redact


ALLOWED_LOG_SUFFIXES = {".log", ".txt", ".json", ".jsonl"}


class LocalLogTools:
    """Bounded, read-only access to files beneath the configured log root."""

    def __init__(self, root: Path, max_bytes: int = 5 * 1024 * 1024):
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def _safe_path(self, relative_or_absolute: str) -> Path:
        raw = Path(relative_or_absolute)
        candidate = raw.resolve() if raw.is_absolute() else (self.root / raw).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Log path is outside configured LOG_ROOT") from exc
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(candidate)
        if candidate.suffix.lower() not in ALLOWED_LOG_SUFFIXES:
            raise ValueError(f"Unsupported log-file type: {candidate.suffix}")
        return candidate

    def _text(self, path: str) -> tuple[str, bool]:
        candidate = self._safe_path(path)
        size = candidate.stat().st_size
        with candidate.open("rb") as handle:
            truncated = size > self.max_bytes
            if truncated:
                handle.seek(-self.max_bytes, 2)
            payload = handle.read(self.max_bytes)
        return redact(payload.decode("utf-8", errors="replace")), truncated

    def _lines(self, path: str) -> tuple[list[str], bool]:
        text, truncated = self._text(path)
        return text.splitlines(), truncated

    def list_logs(self, application: str | None = None, limit: int = 50) -> ToolResult:
        limit = max(1, min(int(limit), 100))
        needle = (application or "").lower()
        entries = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_LOG_SUFFIXES:
                continue
            relative = path.relative_to(self.root)
            if needle and needle not in str(relative).lower():
                continue
            stat = path.stat()
            entries.append(
                {
                    "path": str(relative),
                    "size_bytes": stat.st_size,
                    "modified_epoch": stat.st_mtime,
                }
            )
        entries.sort(key=lambda item: item["modified_epoch"], reverse=True)
        selected = entries[:limit]
        return ToolResult(
            source=EvidenceSource.LOG,
            category=EvidenceCategory.OPERATIONAL,
            summary=f"Discovered {len(selected)} allowlisted local log files",
            content=json.dumps(selected, indent=2),
            metadata={"application": application, "limit": limit, "root": str(self.root)},
            substantive=bool(selected),
        )

    def inspect_summary(self, path: str) -> ToolResult:
        lines, truncated = self._lines(path)
        severity: Counter[str] = Counter()
        exceptions: Counter[str] = Counter()
        for line in lines:
            for level in ("FATAL", "ERROR", "WARN", "INFO", "DEBUG"):
                if re.search(rf"\b{level}\b", line, re.IGNORECASE):
                    severity[level] += 1
                    break
            for match in re.findall(r"\b[A-Za-z0-9_.]*(?:Exception|Error)\b", line):
                exceptions[match] += 1
        summary = (
            f"{len(lines)} bounded lines; severity={dict(severity)}; "
            f"exceptions={dict(exceptions.most_common(8))}"
        )
        content = "\n".join(lines[-20:])
        return ToolResult(
            source=EvidenceSource.LOG,
            category=EvidenceCategory.OPERATIONAL,
            summary=summary,
            content=content,
            metadata={"path": path, "line_count": len(lines), "tail_truncated": truncated},
            substantive=bool(lines),
        )

    def search(self, path: str, query: str, max_matches: int = 20) -> ToolResult:
        if not query or len(query) > 200:
            raise ValueError("Log search query must contain 1-200 characters")
        max_matches = max(1, min(int(max_matches), 50))
        lines, truncated = self._lines(path)
        needle = query.casefold()
        matches = []
        for index, line in enumerate(lines, start=1):
            if needle in line.casefold():
                matches.append(f"{index}: {line}")
                if len(matches) >= max_matches:
                    break
        return ToolResult(
            source=EvidenceSource.LOG,
            category=EvidenceCategory.OPERATIONAL,
            summary=f"Found {len(matches)} literal log matches for {query!r}",
            content="\n".join(matches) if matches else "No matches",
            metadata={
                "query": query,
                "path": path,
                "match_count": len(matches),
                "tail_truncated": truncated,
            },
            substantive=bool(matches),
        )

    def context(self, path: str, line_number: int, before: int = 4, after: int = 6) -> ToolResult:
        before = max(0, min(int(before), 20))
        after = max(0, min(int(after), 20))
        lines, truncated = self._lines(path)
        if not 1 <= line_number <= len(lines):
            raise ValueError(f"line_number must be between 1 and {len(lines)}")
        start = max(1, line_number - before)
        end = min(len(lines), line_number + after)
        excerpt = [f"{index}: {lines[index - 1]}" for index in range(start, end + 1)]
        return ToolResult(
            source=EvidenceSource.LOG,
            category=EvidenceCategory.OPERATIONAL,
            summary=f"Log context around bounded line {line_number}",
            content="\n".join(excerpt),
            metadata={
                "path": path,
                "start_line": start,
                "end_line": end,
                "tail_truncated": truncated,
            },
        )

    def parse_stack_trace(self, text: str) -> ToolResult:
        text = redact(text[:50_000])
        exception_types = re.findall(r"\b[A-Za-z0-9_.]*(?:Exception|Error)\b", text)
        java_frames = re.findall(r"\bat\s+([A-Za-z0-9_.$]+\.[A-Za-z0-9_$<>]+)\(([^)]*)\)", text)
        python_frames = re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)', text)
        content = {
            "exceptions": list(dict.fromkeys(exception_types))[:25],
            "java_frames": [
                {"method": method, "location": location} for method, location in java_frames[:25]
            ],
            "python_frames": [
                {"file": Path(path).name, "line": int(line), "function": function.strip()}
                for path, line, function in python_frames[:25]
            ],
        }
        return ToolResult(
            source=EvidenceSource.LOG,
            category=EvidenceCategory.OPERATIONAL,
            summary="Parsed a bounded, redacted stack trace",
            content=json.dumps(content, indent=2),
            substantive=bool(exception_types or java_frames or python_frames),
        )
