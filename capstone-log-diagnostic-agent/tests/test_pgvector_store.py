from log_diagnostic_agent.stores.pgvector_store import PgVectorIncidentStore


class FakeEmbedder:
    dimension = 3

    def embed(self, text: str) -> list[float]:
        assert text == "diagnostic text"
        return [0.1, 0.2, 0.3]


class FakeVector:
    def __init__(self, values):
        self.values = values


def test_embedding_wraps_plain_list_in_pgvector_adapter_type():
    store = object.__new__(PgVectorIncidentStore)
    store.embedder = FakeEmbedder()
    store._Vector = FakeVector

    vector = store._embedding("diagnostic text")

    assert isinstance(vector, FakeVector)
    assert vector.values == [0.1, 0.2, 0.3]
