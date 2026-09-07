from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonlIncidentMemory:
    """Simple demo persistence. Production state can use LangGraph PostgresSaver."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")
