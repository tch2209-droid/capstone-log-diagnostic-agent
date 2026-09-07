from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_PROJECT_ROOTS = {
    "AddressStandardizationAPI": Path(r"C:\AI_Repo\AddressStandardizationAPI"),
    "AgenticCourseFiles": Path(r"C:\AI_Repo\AgenticCourseFiles"),
    "InsuranceAgentMessageService": Path(r"C:\AI_Repo\InsuranceAgentMessageService"),
    "InsuranceCallCenter": Path(r"C:\AI_Repo\InsuranceCallCenter"),
    "PropertyCasualtyInsuranceAgentInfo": Path(
        r"C:\AI_Repo\PropertyCasualtyInsuranceAgentInfo"
    ),
}

DEFAULT_AGENT_INSTRUCTIONS_FILE = Path(__file__).resolve().parents[2] / "agentinstructions.json"


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _project_roots() -> dict[str, Path]:
    raw = os.getenv("PROJECT_ROOTS_JSON")
    configured = json.loads(raw) if raw else DEFAULT_PROJECT_ROOTS
    if not isinstance(configured, dict) or not configured:
        raise ValueError("PROJECT_ROOTS_JSON must be a non-empty JSON object")
    return {str(name): Path(path).expanduser().resolve() for name, path in configured.items()}


@dataclass(frozen=True)
class Settings:
    log_root: Path
    project_roots: dict[str, Path] = field(default_factory=dict)
    agent_instructions_file: Path = DEFAULT_AGENT_INSTRUCTIONS_FILE
    max_steps: int = 12
    max_tool_calls: int = 10
    max_duration_seconds: int = 180
    max_retries: int = 2
    max_branches: int = 3
    max_branch_depth: int = 3
    max_log_bytes: int = 5 * 1024 * 1024
    max_source_bytes: int = 1024 * 1024
    database_url: str | None = None
    checkpoint_database_url: str | None = None
    llm_model: str = "gpt-5.3-codex"
    reasoning_effort: str = "medium"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    use_pgvector: bool = True
    require_human_review: bool = True
    review_ui_url: str = "http://127.0.0.1:3000"
    review_ui_poll_seconds: float = 2.0
    orchestration_ui_enabled: bool = True
    orchestration_demo_delay_seconds: float = 1.0
    audit_log: Path = Path("data/agent_audit.jsonl")
    atlassian_mcp_url: str | None = None
    atlassian_mcp_auth_mode: str = "oauth"
    atlassian_oauth_callback_port: int = 8765
    atlassian_cloud_id: str | None = None
    atlassian_mcp_email: str | None = None
    atlassian_mcp_api_token: str | None = None
    atlassian_search_tool: str = "searchAtlassian"
    atlassian_fetch_tool: str = "fetchAtlassian"
    atlassian_jira_project_key: str = "SCRUM"
    atlassian_jira_site_url: str = "https://agentic-dev-tacme.atlassian.net"
    atlassian_jira_issue_type: str = "Task"
    atlassian_jira_create_tool: str = "createJiraIssue"
    atlassian_jira_search_tool: str = "searchJiraIssuesUsingJql"

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> "Settings":
        base_dir = (base_dir or Path.cwd()).resolve()
        raw_root = Path(os.getenv("LOG_ROOT", r"C:\AI_Repo\logs"))
        if not raw_root.is_absolute():
            raw_root = base_dir / raw_root
        raw_audit = Path(os.getenv("AUDIT_LOG", "./data/agent_audit.jsonl"))
        if not raw_audit.is_absolute():
            raw_audit = base_dir / raw_audit
        raw_instructions = Path(
            os.getenv("AGENT_INSTRUCTIONS_FILE", "./agentinstructions.json")
        )
        if not raw_instructions.is_absolute():
            raw_instructions = base_dir / raw_instructions
        reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "medium").lower()
        if reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("LLM_REASONING_EFFORT must be low, medium, high, or xhigh")
        atlassian_auth_mode = os.getenv("ATLASSIAN_MCP_AUTH_MODE", "oauth").lower()
        if atlassian_auth_mode not in {"oauth", "api_token"}:
            raise ValueError(
                "ATLASSIAN_MCP_AUTH_MODE must be oauth or api_token"
            )
        return cls(
            log_root=raw_root.resolve(),
            project_roots=_project_roots(),
            agent_instructions_file=raw_instructions.resolve(),
            max_steps=_bounded_int("MAX_STEPS", 12, 1, 50),
            max_tool_calls=_bounded_int("MAX_TOOL_CALLS", 10, 1, 50),
            max_duration_seconds=_bounded_int("MAX_DURATION_SECONDS", 180, 10, 3600),
            max_retries=_bounded_int("MAX_RETRIES", 2, 0, 10),
            max_branches=_bounded_int("MAX_BRANCHES", 3, 1, 3),
            max_branch_depth=_bounded_int("MAX_BRANCH_DEPTH", 3, 1, 3),
            max_log_bytes=_bounded_int(
                "MAX_LOG_BYTES", 5 * 1024 * 1024, 1024, 50 * 1024 * 1024
            ),
            max_source_bytes=_bounded_int(
                "MAX_SOURCE_BYTES", 1024 * 1024, 1024, 10 * 1024 * 1024
            ),
            database_url=os.getenv("DATABASE_URL") or None,
            checkpoint_database_url=os.getenv("CHECKPOINT_DATABASE_URL") or None,
            llm_model=os.getenv("LLM_MODEL", "gpt-5.3-codex"),
            reasoning_effort=reasoning_effort,
            embedding_model=os.getenv(
                "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            use_pgvector=os.getenv("USE_PGVECTOR", "true").lower()
            in {"1", "true", "yes", "on"},
            require_human_review=os.getenv("REQUIRE_HUMAN_REVIEW", "true").lower()
            not in {"0", "false", "no", "off"},
            review_ui_url=os.getenv(
                "SIGNALDESK_UI_URL", "http://127.0.0.1:3000"
            ).rstrip("/"),
            review_ui_poll_seconds=float(
                os.getenv("SIGNALDESK_REVIEW_POLL_SECONDS", "2")
            ),
            orchestration_ui_enabled=os.getenv(
                "SIGNALDESK_ORCHESTRATION_UI_ENABLED", "true"
            ).lower() not in {"0", "false", "no", "off"},
            orchestration_demo_delay_seconds=max(
                0.0,
                min(
                    10.0,
                    float(os.getenv("SIGNALDESK_ORCHESTRATION_STEP_DELAY_SECONDS", "1")),
                ),
            ),
            audit_log=raw_audit.resolve(),
            atlassian_mcp_url=os.getenv("ATLASSIAN_MCP_URL") or None,
            atlassian_mcp_auth_mode=atlassian_auth_mode,
            atlassian_oauth_callback_port=_bounded_int(
                "ATLASSIAN_OAUTH_CALLBACK_PORT", 8765, 1024, 65535
            ),
            atlassian_cloud_id=os.getenv("ATLASSIAN_CLOUD_ID") or None,
            atlassian_mcp_email=os.getenv("ATLASSIAN_MCP_EMAIL") or None,
            atlassian_mcp_api_token=os.getenv("ATLASSIAN_MCP_API_TOKEN") or None,
            atlassian_search_tool=os.getenv("ATLASSIAN_SEARCH_TOOL", "searchAtlassian"),
            atlassian_fetch_tool=os.getenv("ATLASSIAN_FETCH_TOOL", "fetchAtlassian"),
            atlassian_jira_project_key=os.getenv(
                "ATLASSIAN_JIRA_PROJECT_KEY", "SCRUM"
            ),
            atlassian_jira_site_url=os.getenv(
                "ATLASSIAN_JIRA_SITE_URL",
                "https://agentic-dev-tacme.atlassian.net",
            ).rstrip("/"),
            atlassian_jira_issue_type=os.getenv("ATLASSIAN_JIRA_ISSUE_TYPE", "Task"),
            atlassian_jira_create_tool=os.getenv(
                "ATLASSIAN_JIRA_CREATE_TOOL", "createJiraIssue"
            ),
            atlassian_jira_search_tool=os.getenv(
                "ATLASSIAN_JIRA_SEARCH_TOOL", "searchJiraIssuesUsingJql"
            ),
        )
