from pathlib import Path

import pytest

from log_diagnostic_agent.tools.local_logs import LocalLogTools
from log_diagnostic_agent.tools.operational import OperationalTools


def test_log_reader_blocks_paths_outside_configured_root(tmp_path: Path):
    root = tmp_path / "logs"
    root.mkdir()
    outside = tmp_path / "secret.log"
    outside.write_text("password=do-not-read", encoding="utf-8")
    tools = LocalLogTools(root)
    with pytest.raises(ValueError, match="outside configured LOG_ROOT"):
        tools.inspect_summary(str(outside))


def test_log_output_redacts_api_keys(tmp_path: Path):
    root = tmp_path / "logs"
    root.mkdir()
    (root / "app.log").write_text("ERROR api_key=super-secret failure", encoding="utf-8")
    result = LocalLogTools(root).search("app.log", "ERROR")
    assert "super-secret" not in result.content
    assert "[REDACTED]" in result.content


def test_source_search_is_limited_to_named_projects(tmp_path: Path):
    source = tmp_path / "app"
    source.mkdir()
    (source / "main.py").write_text("raise RuntimeError('boom')", encoding="utf-8")
    tools = OperationalTools({"AllowedApp": source}, tmp_path)
    assert tools.search_source_code("RuntimeError", "AllowedApp").substantive
    with pytest.raises(ValueError, match="Unknown application"):
        tools.search_source_code("RuntimeError", "OtherApp")
