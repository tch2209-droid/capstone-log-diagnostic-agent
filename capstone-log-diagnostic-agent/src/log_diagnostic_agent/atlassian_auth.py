from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .tools.jira import (
    AtlassianRovoJiraProvider,
    _exception_summary,
    jira_provider_from_settings,
)


def main() -> None:
    """Authenticate to Atlassian MCP and verify Jira tools without writing data."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional dependency
        load_dotenv = None

    parser = argparse.ArgumentParser(
        description="Authenticate to Atlassian MCP and inspect available tools"
    )
    parser.add_argument(
        "--show-schema",
        metavar="TOOL",
        help="Print the live input schema for one MCP tool after authentication",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    if load_dotenv:
        load_dotenv(root / ".env")

    provider = jira_provider_from_settings(Settings.from_env(root))
    if not isinstance(provider, AtlassianRovoJiraProvider):
        raise SystemExit(
            "Atlassian MCP is not configured. Set ATLASSIAN_MCP_URL and "
            "ATLASSIAN_CLOUD_ID in .env."
        )

    print("-" * 88, flush=True)
    print("[ATLASSIAN MCP PREFLIGHT] Authenticating SignalDesk", flush=True)
    print(f"  Endpoint : {provider.url}", flush=True)
    print(f"  Auth mode: {provider.auth_mode}", flush=True)
    if provider.auth_mode == "oauth":
        print(
            "  Browser  : Atlassian sign-in will open if no valid saved token exists",
            flush=True,
        )
        print(
            "  Callback : "
            f"http://localhost:{provider.oauth_callback_port}/callback",
            flush=True,
        )
    print("  Safety   : read-only tool discovery; no Jira ticket will be created", flush=True)

    try:
        tool_names = provider.authenticate_and_list_tools()
    except Exception as exc:
        raise SystemExit(f"Atlassian MCP preflight failed: {_exception_summary(exc)}") from exc

    missing = [
        name
        for name in (provider.search_tool, provider.create_tool)
        if name not in tool_names
    ]
    print(f"  Connected: {len(tool_names)} MCP tools discovered", flush=True)
    print(f"  Jira read: {provider.search_tool}", flush=True)
    print(f"  Jira write: {provider.create_tool}", flush=True)
    if missing:
        raise SystemExit(
            "Authentication succeeded, but required Jira tools are unavailable: "
            + ", ".join(missing)
        )
    print("[ATLASSIAN MCP PREFLIGHT] READY - Jira delivery tools are available", flush=True)
    if args.show_schema:
        print(json.dumps(provider.get_tool_schema(args.show_schema), indent=2))


if __name__ == "__main__":
    main()
