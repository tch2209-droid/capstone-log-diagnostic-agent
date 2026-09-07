from __future__ import annotations

from typing import Protocol

from ..models import IncidentRecord, SimilarIncident


class IncidentRAGStore(Protocol):
    def search(
        self,
        query: str,
        top_k: int = 3,
        application: str | None = None,
    ) -> list[SimilarIncident]: ...

    def add(self, record: IncidentRecord) -> None: ...
