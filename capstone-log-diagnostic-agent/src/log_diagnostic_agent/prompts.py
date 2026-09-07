from __future__ import annotations

import json
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any


@dataclass(frozen=True)
class AgentInstructions:
    """Validated contents of the external agent instructions document."""

    supervisor_prompt: str
    hypothesis_prompt: str
    branch_prompt: str
    critic_prompt: str
    triage_recorded_message: str
    evidence_recorded_message: str
    schema_validation_failed_message: str
    evidence_gate_rejected_message: str
    default_incident_description: str
    tool_descriptions: dict[str, str]

    def render(self, name: str, **values: object) -> str:
        template = getattr(self, name)
        if not isinstance(template, str):
            raise TypeError(f"Instruction {name!r} is not a renderable template")
        try:
            return Template(template).substitute(
                {key: str(value) for key, value in values.items()}
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Could not render agent instruction {name!r}: {exc}") from exc


def _as_text(name: str, value: Any) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, list) and all(isinstance(line, str) for line in value):
        text = "\n".join(value)
    else:
        raise ValueError(
            f"Agent instruction {name!r} must be a string or an array of strings"
        )
    text = text.strip()
    if not text:
        raise ValueError(f"Agent instruction {name!r} cannot be empty")
    return text


@lru_cache(maxsize=None)
def load_agent_instructions(path: Path) -> AgentInstructions:
    """Load all agent-facing prompts from a JSON file outside the package."""

    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Agent instructions file does not exist: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Agent instructions file is not valid JSON: {resolved}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Agent instructions must be a JSON object: {resolved}")

    text_fields = {field.name for field in fields(AgentInstructions)} - {"tool_descriptions"}
    missing = sorted((text_fields | {"tool_descriptions"}) - payload.keys())
    if missing:
        raise ValueError(f"Agent instructions are missing: {', '.join(missing)}")

    raw_descriptions = payload["tool_descriptions"]
    if not isinstance(raw_descriptions, dict):
        raise ValueError("Agent instruction 'tool_descriptions' must be a JSON object")
    required_tools = {
        "list_logs",
        "inspect_log_summary",
        "search_logs",
        "get_log_context",
        "query_metrics",
        "search_source_code",
        "get_recent_changes",
        "search_confluence_mcp",
        "search_validated_incidents",
    }
    missing_tools = sorted(required_tools - raw_descriptions.keys())
    if missing_tools:
        raise ValueError(f"Agent tool descriptions are missing: {', '.join(missing_tools)}")

    descriptions = {
        name: _as_text(f"tool_descriptions.{name}", raw_descriptions[name])
        for name in required_tools
    }
    instructions = AgentInstructions(
        **{name: _as_text(name, payload[name]) for name in text_fields},
        tool_descriptions=descriptions,
    )

    # Render each template once so malformed placeholders fail at startup.
    instructions.render(
        "supervisor_prompt",
        incident_json="{}",
        evidence_json="[]",
        step_count=0,
        max_steps=1,
    )
    instructions.render(
        "hypothesis_prompt", draft_json="{}", evidence_json="[]"
    )
    instructions.render(
        "branch_prompt", hypothesis_json="{}", evidence_json="[]"
    )
    instructions.render("critic_prompt", branches_json="[]")
    instructions.render("triage_recorded_message", evidence_id="E1", summary="summary")
    instructions.render("evidence_recorded_message", evidence_id="E1", summary="summary")
    instructions.render("evidence_gate_rejected_message", reasons="reason")
    return instructions


def system_prompt(
    instructions: AgentInstructions,
    incident: dict,
    evidence: list[dict],
    step_count: int,
    max_steps: int,
) -> str:
    return instructions.render(
        "supervisor_prompt",
        incident_json=json.dumps(incident, indent=2),
        evidence_json=json.dumps(evidence, indent=2, default=str),
        step_count=step_count,
        max_steps=max_steps,
    )
