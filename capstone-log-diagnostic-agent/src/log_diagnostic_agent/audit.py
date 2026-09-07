from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact


class AuditLogger:
    """Append-only, redacted runtime audit trail for safety and evaluation events."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event_type: str, incident_id: str, **details: Any) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "incident_id": incident_id,
            "details": details,
        }
        line = redact(json.dumps(payload, default=str, separators=(",", ":")))
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
