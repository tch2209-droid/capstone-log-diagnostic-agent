import pytest

from log_diagnostic_agent.stores.checkpoint import (
    checkpoint_connection_url,
    is_cockroach_url,
)


def test_cockroach_url_detection() -> None:
    assert is_cockroach_url(
        "postgresql://user:secret@cluster.aws-us-east-1.cockroachlabs.cloud:26257/app"
    )
    assert not is_cockroach_url("postgresql://localhost:5432/app")


def test_cockroach_requires_a_separate_checkpoint_database() -> None:
    with pytest.raises(ValueError, match="CHECKPOINT_DATABASE_URL is required"):
        checkpoint_connection_url(
            "postgresql://cluster.cockroachlabs.cloud/app",
            None,
        )


def test_supabase_checkpoint_url_takes_precedence() -> None:
    supabase = "postgresql://postgres:secret@db.project.supabase.co:5432/postgres"
    assert (
        checkpoint_connection_url(
            "postgresql://cluster.cockroachlabs.cloud/app",
            supabase,
        )
        == supabase
    )


def test_cockroach_checkpoint_override_is_rejected() -> None:
    with pytest.raises(ValueError, match="must target PostgreSQL"):
        checkpoint_connection_url(
            None,
            "postgresql://cluster.cockroachlabs.cloud/checkpoints",
        )


def test_placeholder_password_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"Replace \[YOUR-PASSWORD\]"):
        checkpoint_connection_url(
            None,
            "postgresql://postgres:[YOUR-PASSWORD]@db.project.supabase.co/postgres",
        )
