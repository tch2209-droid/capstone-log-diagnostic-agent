from __future__ import annotations

import json

from ..embeddings import Embedder
from ..models import IncidentRecord, SimilarIncident


class PgVectorIncidentStore:
    """PostgreSQL + pgvector implementation for validated incident RAG."""

    def __init__(self, database_url: str, embedder: Embedder):
        try:
            import psycopg
            from pgvector import Vector
            from pgvector.psycopg import register_vector
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install PostgreSQL support: pip install -e '.[postgres]'") from exc
        self._psycopg = psycopg
        self._Vector = Vector
        self._register_vector = register_vector
        self.database_url = database_url
        self.embedder = embedder
        if embedder.dimension != 384:
            raise ValueError("The bundled SQL schema expects 384-dimensional embeddings")

    def setup(self) -> None:
        """Create the trusted-memory table on PostgreSQL-compatible databases."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS validated_incidents (
                    incident_id TEXT PRIMARY KEY,
                    application TEXT NOT NULL,
                    component TEXT,
                    error_family TEXT,
                    symptoms TEXT NOT NULL,
                    validated_diagnosis TEXT NOT NULL,
                    evidence_summary TEXT NOT NULL,
                    resolution TEXT,
                    validation_status TEXT NOT NULL CHECK (validation_status = 'validated'),
                    review_status TEXT NOT NULL CHECK (review_status IN ('confirmed', 'corrected')),
                    reviewed_by TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    embedding VECTOR(384) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                "ALTER TABLE validated_incidents "
                "ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'confirmed'"
            )
            cur.execute(
                "ALTER TABLE validated_incidents "
                "ADD COLUMN IF NOT EXISTS reviewed_by TEXT NOT NULL DEFAULT 'legacy_import'"
            )
            conn.commit()

    def _connect(self):
        conn = self._psycopg.connect(self.database_url)
        self._register_vector(conn)
        return conn

    def _embedding(self, text: str):
        """Return the explicit pgvector value expected by Psycopg's adapter."""
        return self._Vector(self.embedder.embed(text))

    @staticmethod
    def _text(record: IncidentRecord) -> str:
        return "\n".join(
            filter(
                None,
                [
                    record.application,
                    record.component,
                    record.error_family,
                    record.symptoms,
                    record.validated_diagnosis,
                    record.evidence_summary,
                    record.resolution,
                ],
            )
        )

    def add(self, record: IncidentRecord) -> None:
        if record.validation_status != "validated":
            raise ValueError("Only validated incidents may be indexed")
        if record.review_status not in {"confirmed", "corrected"}:
            raise ValueError("Only reviewer-confirmed or reviewer-corrected incidents may be indexed")
        vector = self._embedding(self._text(record))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO validated_incidents (
                    incident_id, application, component, error_family, symptoms,
                    validated_diagnosis, evidence_summary, resolution,
                    validation_status, review_status, reviewed_by, metadata, embedding
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'validated',%s,%s,%s,%s)
                ON CONFLICT (incident_id) DO UPDATE SET
                    application=EXCLUDED.application,
                    component=EXCLUDED.component,
                    error_family=EXCLUDED.error_family,
                    symptoms=EXCLUDED.symptoms,
                    validated_diagnosis=EXCLUDED.validated_diagnosis,
                    evidence_summary=EXCLUDED.evidence_summary,
                    resolution=EXCLUDED.resolution,
                    review_status=EXCLUDED.review_status,
                    reviewed_by=EXCLUDED.reviewed_by,
                    metadata=EXCLUDED.metadata,
                    embedding=EXCLUDED.embedding
                """,
                (
                    record.incident_id,
                    record.application,
                    record.component,
                    record.error_family,
                    record.symptoms,
                    record.validated_diagnosis,
                    record.evidence_summary,
                    record.resolution,
                    record.review_status,
                    record.reviewed_by,
                    json.dumps(record.metadata),
                    vector,
                ),
            )
            conn.commit()

    def search(self, query: str, top_k: int = 3, application: str | None = None) -> list[SimilarIncident]:
        vector = self._embedding(query)
        where = "validation_status = 'validated'"
        if application:
            where += " AND application = %s"
        sql = f"""
            SELECT incident_id, application, component, error_family, symptoms,
                   validated_diagnosis, evidence_summary, resolution,
                   validation_status, review_status, reviewed_by, metadata,
                   1 - (embedding <=> %s) AS similarity
            FROM validated_incidents
            WHERE {where}
            ORDER BY embedding <=> %s
            LIMIT %s
        """
        # The embedding is used once for the score and once for ordering.
        if application:
            execute_params = [vector, application, vector, top_k]
        else:
            execute_params = [vector, vector, top_k]
        results: list[SimilarIncident] = []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, execute_params)
            for row in cur.fetchall():
                record = IncidentRecord(
                    incident_id=row[0],
                    application=row[1],
                    component=row[2],
                    error_family=row[3],
                    symptoms=row[4],
                    validated_diagnosis=row[5],
                    evidence_summary=row[6],
                    resolution=row[7],
                    validation_status="validated",
                    review_status=row[9],
                    reviewed_by=row[10],
                    metadata=row[11] or {},
                )
                results.append(SimilarIncident(score=float(row[12]), record=record))
        return results
