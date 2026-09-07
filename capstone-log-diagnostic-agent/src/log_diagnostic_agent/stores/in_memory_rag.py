from __future__ import annotations

import json
from pathlib import Path

from ..embeddings import Embedder, HashingEmbedder, cosine_similarity
from ..models import IncidentRecord, SimilarIncident


class InMemoryIncidentRAG:
    def __init__(self, records: list[IncidentRecord], embedder: Embedder | None = None):
        self.embedder = embedder or HashingEmbedder()
        self._records: dict[str, IncidentRecord] = {
            record.incident_id: record for record in records if record.validation_status == "validated"
        }
        self._vectors: dict[str, list[float]] = {
            incident_id: self.embedder.embed(self._text(record))
            for incident_id, record in self._records.items()
        }

    @classmethod
    def from_json(cls, path: Path, embedder: Embedder | None = None) -> "InMemoryIncidentRAG":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls([IncidentRecord.model_validate(item) for item in payload], embedder=embedder)

    @staticmethod
    def _text(record: IncidentRecord) -> str:
        return "\n".join(
            [
                record.application,
                record.component or "",
                record.error_family or "",
                record.symptoms,
                record.validated_diagnosis,
                record.evidence_summary,
                record.resolution or "",
            ]
        )

    def search(
        self,
        query: str,
        top_k: int = 3,
        application: str | None = None,
    ) -> list[SimilarIncident]:
        query_vector = self.embedder.embed(query)
        results: list[SimilarIncident] = []
        for incident_id, record in self._records.items():
            if application and record.application != application:
                continue
            score = cosine_similarity(query_vector, self._vectors[incident_id])
            results.append(SimilarIncident(score=score, record=record))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def add(self, record: IncidentRecord) -> None:
        if record.validation_status != "validated":
            raise ValueError("Only validated incidents may be added to the RAG corpus")
        self._records[record.incident_id] = record
        self._vectors[record.incident_id] = self.embedder.embed(self._text(record))

    def __len__(self) -> int:
        return len(self._records)
