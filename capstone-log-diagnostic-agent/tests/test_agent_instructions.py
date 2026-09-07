import json
from pathlib import Path

import pytest

from log_diagnostic_agent.prompts import load_agent_instructions, system_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_external_agent_instructions_load_and_render():
    instructions = load_agent_instructions(PROJECT_ROOT / "agentinstructions.json")

    prompt = system_prompt(
        instructions,
        {"incident_id": "INC-123"},
        [{"evidence_id": "E1"}],
        step_count=2,
        max_steps=12,
    )

    assert "INC-123" in prompt
    assert '"evidence_id": "E1"' in prompt
    assert "Step: 2/12" in prompt
    assert instructions.tool_descriptions["search_logs"]


def test_external_agent_instructions_require_every_entry(tmp_path):
    incomplete = tmp_path / "agentinstructions.json"
    incomplete.write_text(json.dumps({"supervisor_prompt": "test"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Agent instructions are missing"):
        load_agent_instructions(incomplete)
