from __future__ import annotations

from contextlib import contextmanager
from urllib.parse import urlparse


def is_cockroach_url(database_url: str) -> bool:
    """Return whether a PostgreSQL URL targets CockroachDB Cloud."""
    hostname = (urlparse(database_url).hostname or "").lower()
    return hostname.endswith(".cockroachlabs.cloud") or "cockroach" in hostname


def checkpoint_connection_url(
    database_url: str | None, checkpoint_database_url: str | None
) -> str:
    """Select a real PostgreSQL URL for LangGraph checkpoint persistence."""
    if checkpoint_database_url:
        if "[YOUR-PASSWORD]" in checkpoint_database_url:
            raise ValueError(
                "Replace [YOUR-PASSWORD] in CHECKPOINT_DATABASE_URL before starting the agent"
            )
        if is_cockroach_url(checkpoint_database_url):
            raise ValueError("CHECKPOINT_DATABASE_URL must target PostgreSQL, not CockroachDB")
        return checkpoint_database_url
    if database_url and not is_cockroach_url(database_url):
        return database_url
    raise ValueError(
        "CHECKPOINT_DATABASE_URL is required for LangGraph checkpoints when "
        "DATABASE_URL targets CockroachDB"
    )


@contextmanager
def open_checkpointer(
    *,
    database_url: str | None,
    checkpoint_database_url: str | None,
):
    """Open the PostgreSQL-backed LangGraph checkpointer."""
    from langgraph.checkpoint.postgres import PostgresSaver

    connection_url = checkpoint_connection_url(database_url, checkpoint_database_url)
    with PostgresSaver.from_conn_string(connection_url) as saver:
        saver.setup()
        yield saver
