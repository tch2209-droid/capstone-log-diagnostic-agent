from pathlib import Path

from log_diagnostic_agent.stores.in_memory_rag import InMemoryIncidentRAG


DATA = Path(__file__).resolve().parents[1] / "data"


def test_similar_hikari_incident_is_ranked_first():
    rag = InMemoryIncidentRAG.from_json(DATA / "validated_incidents.json")
    results = rag.search(
        "HikariPool connection timeout active max idle zero slow order_history customer_reference",
        application="order-service",
        top_k=3,
    )
    assert results
    assert results[0].record.incident_id == "INC-1001"
    assert all(item.record.validation_status == "validated" for item in results)
