from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from ..config import Settings
from ..models import DiagnosisReport, HumanReview, JiraTicketResult


class JiraTicketProvider(Protocol):
    def create_or_get_ticket(
        self,
        incident: dict,
        report: DiagnosisReport,
        review: HumanReview,
        diagnosis_id: str | None,
    ) -> JiraTicketResult: ...


class DisabledJiraTicketProvider:
    def create_or_get_ticket(
        self,
        incident: dict,
        report: DiagnosisReport,
        review: HumanReview,
        diagnosis_id: str | None,
    ) -> JiraTicketResult:
        return JiraTicketResult(
            status="not_configured",
            diagnosis_id=diagnosis_id,
            error=(
                "Jira delivery is not configured in the LangGraph runtime; set the "
                "ATLASSIAN_MCP_* environment variables."
            ),
        )


def _safe_label(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]", "-", value.lower())
    return re.sub(r"-+", "-", cleaned).strip("-")[:255]


def _find_issue(value: Any) -> tuple[str | None, str] | None:
    if isinstance(value, str):
        match = re.search(r"\b([A-Z][A-Z0-9]+-\d+)\b", value)
        return (None, match.group(1)) if match else None
    if isinstance(value, list):
        for child in value:
            found = _find_issue(child)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    key = value.get("key")
    if isinstance(key, str) and re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", key):
        issue_id = value.get("id")
        return (str(issue_id) if issue_id is not None else None, key)
    for child in value.values():
        found = _find_issue(child)
        if found:
            return found
    return None


def _result_values(result: Any) -> list[Any]:
    values: list[Any] = []

    def collect(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            try:
                values.append(json.loads(value))
            except (TypeError, json.JSONDecodeError):
                values.append(value)
            return
        if isinstance(value, list):
            for child in value:
                collect(child)
            return
        if isinstance(value, dict):
            structured = value.get("structured_content") or value.get(
                "structuredContent"
            )
            if structured is not None:
                collect(structured)
            if value.get("type") == "text" and value.get("text"):
                collect(value["text"])
            else:
                values.append(value)
            return

        structured = getattr(value, "structuredContent", None)
        if structured is not None:
            collect(structured)
        artifact = getattr(value, "artifact", None)
        if artifact is not None:
            collect(artifact)
        content = getattr(value, "content", None)
        if content is not None:
            collect(content)

    collect(result)
    return values


def _redact_error(value: str) -> str:
    value = re.sub(r"Basic\s+[A-Za-z0-9+/=]+", "Basic [redacted]", value)
    value = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [redacted]", value)
    return value


def _exception_summary(exc: BaseException) -> str:
    """Flatten ExceptionGroup/transport wrappers into actionable safe details."""
    messages: list[str] = []
    seen: set[int] = set()

    def visit(current: BaseException) -> None:
        if id(current) in seen:
            return
        seen.add(id(current))
        children = getattr(current, "exceptions", ())
        if children:
            for child in children:
                if isinstance(child, BaseException):
                    visit(child)
        else:
            message = f"{type(current).__name__}: {current}"
            response = getattr(current, "response", None)
            if response is not None:
                status = getattr(response, "status_code", None)
                try:
                    body = str(getattr(response, "text", "") or "").strip()
                except Exception:
                    body = ""
                if status:
                    message += f" | HTTP {status}"
                if body:
                    message += f" | response: {body[:500]}"
            messages.append(_redact_error(message))
        cause = current.__cause__ or current.__context__
        if isinstance(cause, BaseException):
            visit(cause)

    visit(exc)
    unique = list(dict.fromkeys(messages))
    return " | ".join(unique)[:2000] or _redact_error(str(exc))[:2000]


class AtlassianRovoJiraProvider:
    """Deterministic Jira writer used only after the LangGraph review gate."""

    def __init__(
        self,
        *,
        url: str,
        cloud_id: str,
        email: str,
        api_token: str,
        auth_mode: str = "oauth",
        oauth_callback_port: int = 8765,
        project_key: str,
        site_url: str,
        issue_type: str = "Task",
        create_tool: str = "createJiraIssue",
        search_tool: str = "searchJiraIssuesUsingJql",
    ):
        self.url = url
        self.auth_mode = auth_mode
        self.oauth_callback_port = oauth_callback_port
        self.cloud_id = cloud_id
        self.project_key = project_key
        self.site_url = site_url.rstrip("/")
        self.issue_type = issue_type
        self.create_tool = create_tool
        self.search_tool = search_tool
        self.email = email
        self.api_token = api_token
        self._oauth_auth: Any | None = None

    def _connection(self) -> dict[str, Any]:
        connection: dict[str, Any] = {
            "url": self.url,
            "transport": "http",
        }
        if self.auth_mode == "oauth":
            import keyring
            from cryptography.fernet import Fernet
            from fastmcp.client.auth import OAuth
            from key_value.aio.stores.filetree import (
                FileTreeStore,
                FileTreeV1CollectionSanitizationStrategy,
                FileTreeV1KeySanitizationStrategy,
            )
            from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
            from platformdirs import user_data_path

            # Atlassian's token payload is larger than Windows Credential Manager's
            # per-value limit. Store only a small Fernet key in the OS vault and keep
            # the encrypted payload in the user's local application-data folder.
            if self._oauth_auth is None:
                service = "SignalDesk Atlassian MCP"
                username = "oauth-token-encryption-key"
                stored_key = keyring.get_password(service, username)
                if stored_key is None:
                    stored_key = Fernet.generate_key().decode("ascii")
                    keyring.set_password(service, username, stored_key)
                token_directory = (
                    user_data_path("SignalDesk", "SignalDesk")
                    / "atlassian-oauth"
                    / f"callback-{self.oauth_callback_port}"
                )
                token_directory.mkdir(parents=True, exist_ok=True)
                token_storage = FernetEncryptionWrapper(
                    key_value=FileTreeStore(
                        data_directory=token_directory,
                        key_sanitization_strategy=(
                            FileTreeV1KeySanitizationStrategy(token_directory)
                        ),
                        collection_sanitization_strategy=(
                            FileTreeV1CollectionSanitizationStrategy(token_directory)
                        ),
                    ),
                    fernet=Fernet(stored_key.encode("ascii")),
                )
                self._oauth_auth = OAuth(
                    mcp_url=self.url,
                    client_name="SignalDesk LangGraph",
                    token_storage=token_storage,
                    callback_port=self.oauth_callback_port,
                    scopes=[
                        "read:me",
                        "read:account",
                        "email",
                        "offline_access",
                        "read:jira:agent-interface",
                        "write:jira:agent-interface",
                        "search:jira:agent-interface",
                    ],
                )
            connection["auth"] = self._oauth_auth
        else:
            import httpx

            connection["auth"] = httpx.BasicAuth(self.email, self.api_token)
        return connection

    @staticmethod
    def _description(incident: dict, report: DiagnosisReport, review: HumanReview) -> str:
        actions = "\n".join(
            f"{index}. {action}"
            for index, action in enumerate(report.recommended_actions, 1)
        ) or "No potential changes were proposed."
        if report.evidence_details:
            evidence = "\n\n".join(
                (
                    f"### {item.evidence_id} - {item.source}\n\n"
                    f"{item.summary}\n\n"
                    + "\n".join(
                        f"    {line}" for line in item.detail[:4000].splitlines()
                    )
                ).rstrip()
                for item in report.evidence_details
            )
        else:
            evidence = ", ".join(report.evidence_ids) or "None cited"
        return (
            "# SignalDesk approved diagnosis\n\n"
            "## Approval\n\n"
            f"- Approver: {review.reviewer}\n"
            f"- Decision: {review.decision.value}\n"
            f"- Reviewer comments: {review.notes or 'None supplied'}\n"
            f"- Recorded remediation: {review.actual_remediation or 'None supplied'}\n\n"
            "## Incident\n\n"
            f"- Incident ID / ticket reference: {report.incident_id}\n"
            f"- Application: {incident.get('application', 'unknown')}\n"
            f"- Component: {incident.get('component') or 'Not specified'}\n"
            f"- Description: {incident.get('description') or report.immediate_failure}\n"
            f"- Immediate failure: {report.immediate_failure}\n\n"
            "## Approved theory\n\n"
            f"{report.probable_root_cause}\n\n"
            f"- Confidence: {report.confidence:.0%}\n"
            f"- Evidence IDs: {', '.join(report.evidence_ids) or 'None cited'}\n\n"
            "## Supporting code and operational evidence\n\n"
            f"{evidence}\n\n"
            "## Potential changes\n\n"
            f"{actions}\n\n"
            "---\nCreated by the SignalDesk LangGraph Jira node through Atlassian Rovo MCP."
        )

    def _create_arguments(
        self,
        incident: dict,
        report: DiagnosisReport,
        review: HumanReview,
        label: str,
    ) -> dict[str, Any]:
        """Build arguments matching the live Atlassian createJiraIssue schema."""
        return {
            "cloudId": self.cloud_id,
            "projectKey": self.project_key,
            "issueType": self.issue_type,
            "summary": (
                f"[{report.incident_id}] "
                f"{report.probable_root_cause}"
            )[:255],
            "description": self._description(incident, report, review),
            "contentFormat": "markdown",
            "labels": [
                "signaldesk",
                "approved-diagnosis",
                _safe_label(f"incident-{report.incident_id}"),
                label,
            ],
        }

    @asynccontextmanager
    async def _tools_by_name(self) -> AsyncIterator[dict[str, Any]]:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            from langchain_mcp_adapters.tools import load_mcp_tools
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install MCP support: pip install -e '.[mcp]'") from exc

        client = MultiServerMCPClient(
            {"atlassian": self._connection()},
            handle_tool_errors=False,
        )
        async with client.session("atlassian") as session:
            tools = await load_mcp_tools(session, handle_tool_errors=False)
            yield {tool.name: tool for tool in tools}

    async def _list_tool_names(self) -> list[str]:
        async with self._tools_by_name() as tools_by_name:
            return sorted(tools_by_name)

    def authenticate_and_list_tools(self) -> list[str]:
        """Run OAuth/API-token authentication without performing a Jira write."""
        return asyncio.run(self._list_tool_names())

    async def _get_tool_schema(self, tool_name: str) -> dict[str, Any]:
        async with self._tools_by_name() as tools_by_name:
            if tool_name not in tools_by_name:
                raise RuntimeError(f"Atlassian MCP did not expose {tool_name!r}")
            schema = tools_by_name[tool_name].args_schema
            if isinstance(schema, dict):
                return schema
            return schema.model_json_schema()

    def get_tool_schema(self, tool_name: str) -> dict[str, Any]:
        """Return the live MCP input schema without invoking the tool."""
        return asyncio.run(self._get_tool_schema(tool_name))

    async def _create_or_get(
        self,
        incident: dict,
        report: DiagnosisReport,
        review: HumanReview,
        diagnosis_id: str | None,
    ) -> JiraTicketResult:
        stable_id = diagnosis_id or "approved-theory"
        label = _safe_label(f"signaldesk-{report.incident_id}-{stable_id}")
        async with self._tools_by_name() as tools_by_name:
            tool_names = set(tools_by_name)
            if self.create_tool not in tool_names:
                raise RuntimeError(
                    f"Atlassian MCP did not expose {self.create_tool!r} for this identity"
                )

            if self.search_tool in tool_names:
                searched = await tools_by_name[self.search_tool].ainvoke(
                    {
                        "cloudId": self.cloud_id,
                        "jql": (
                            f'project = {self.project_key} AND labels = "{label}" '
                            "ORDER BY created DESC"
                        ),
                        "fields": ["id", "key", "summary"],
                        "maxResults": 50,
                    }
                )
                for value in _result_values(searched):
                    found = _find_issue(value)
                    if found:
                        issue_id, issue_key = found
                        return JiraTicketResult(
                            status="existing",
                            diagnosis_id=diagnosis_id,
                            issue_id=issue_id,
                            issue_key=issue_key,
                            issue_url=f"{self.site_url}/browse/{issue_key}",
                        )

            created = await tools_by_name[self.create_tool].ainvoke(
                self._create_arguments(incident, report, review, label)
            )
            for value in _result_values(created):
                found = _find_issue(value)
                if found:
                    issue_id, issue_key = found
                    return JiraTicketResult(
                        status="created",
                        diagnosis_id=diagnosis_id,
                        issue_id=issue_id,
                        issue_key=issue_key,
                        issue_url=f"{self.site_url}/browse/{issue_key}",
                    )
            raise RuntimeError("Atlassian MCP returned no Jira issue key")

    def create_or_get_ticket(
        self,
        incident: dict,
        report: DiagnosisReport,
        review: HumanReview,
        diagnosis_id: str | None,
    ) -> JiraTicketResult:
        try:
            print(
                "  [ATLASSIAN MCP] LangChain adapter opening a streamable HTTP "
                f"session with {self.auth_mode} authentication.",
                flush=True,
            )
            if self.auth_mode == "oauth":
                print(
                    "  [ATLASSIAN MCP] If consent is required, complete the "
                    "Atlassian sign-in that opens in your browser. The resulting "
                    "token is stored encrypted in your local application data.",
                    flush=True,
                )
            return asyncio.run(
                self._create_or_get(incident, report, review, diagnosis_id)
            )
        except Exception as exc:
            return JiraTicketResult(
                status="failed",
                diagnosis_id=diagnosis_id,
                error=_exception_summary(exc),
            )


def jira_provider_from_settings(settings: Settings) -> JiraTicketProvider:
    required = [settings.atlassian_mcp_url, settings.atlassian_cloud_id]
    if settings.atlassian_mcp_auth_mode == "api_token":
        required.extend(
            [settings.atlassian_mcp_email, settings.atlassian_mcp_api_token]
        )
    if not all(required):
        return DisabledJiraTicketProvider()
    return AtlassianRovoJiraProvider(
        url=settings.atlassian_mcp_url or "",
        cloud_id=settings.atlassian_cloud_id or "",
        email=settings.atlassian_mcp_email or "",
        api_token=settings.atlassian_mcp_api_token or "",
        auth_mode=settings.atlassian_mcp_auth_mode,
        oauth_callback_port=settings.atlassian_oauth_callback_port,
        project_key=settings.atlassian_jira_project_key,
        site_url=settings.atlassian_jira_site_url,
        issue_type=settings.atlassian_jira_issue_type,
        create_tool=settings.atlassian_jira_create_tool,
        search_tool=settings.atlassian_jira_search_tool,
    )
