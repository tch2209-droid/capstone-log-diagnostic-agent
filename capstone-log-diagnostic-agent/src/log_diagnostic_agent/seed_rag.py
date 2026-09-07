from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .embeddings import SentenceTransformerEmbedder
from .models import IncidentRecord
from .stores.pgvector_store import PgVectorIncidentStore


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    settings = Settings.from_env(project_root)
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required")
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    store = PgVectorIncidentStore(settings.database_url, embedder)
    payload = json.loads((settings.log_root / "validated_incidents.json").read_text(encoding="utf-8"))
    count = 0
    for item in payload:
        record = IncidentRecord.model_validate(item)
        store.add(record)
        count += 1
    print(f"Seeded {count} validated incident records into pgvector")


if __name__ == "__main__":
    main()
