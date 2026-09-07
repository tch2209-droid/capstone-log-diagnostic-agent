from __future__ import annotations

import asyncio
import base64
import json
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Protocol

from ..models import EvidenceCategory, EvidenceSource, ToolResult


class ConfluenceProvider(Protocol):
    def search(self, query: str) -> ToolResult: ...


class StubConfluenceProvider:
    """Synthetic local stand-in for Confluence MCP during the capstone demo."""

    def __init__(self, data_root: Path):
        self.path = data_root / "confluence_stub.json"

    def search(self, query: str) -> ToolResult:
        docs = json.loads(self.path.read_text(encoding="utf-8"))
        terms = {term.lower() for term in query.replace("/", " ").split() if len(term) > 2}
        scored = []
        for doc in docs:
            haystack = f"{doc['title']} {doc['content']}".lower()
            score = sum(1 for term in terms if term in haystack)
            scored.append((score, doc))
        selected = [doc for score, doc in sorted(scored, key=lambda x: x[0], reverse=True)[:3] if score > 0]
        if not selected:
            selected = docs[:2]
        return ToolResult(
            source=EvidenceSource.CONFLUENCE,
            category=EvidenceCategory.REFERENCE,
            summary=f"Confluence-style search returned {len(selected)} documents",
            content=json.dumps(selected, indent=2),
            metadata={"query": query, "provider": "synthetic_stub"},
        )


class AtlassianRovoMCPProvider:
    """Read-only adapter for an Atlassian Rovo MCP endpoint.

    The default tool is `searchAtlassian`. The exact server-side schema can
    evolve, so this adapter intentionally keeps its argument mapping small.
    Use `list_tools()` during setup to inspect the tools exposed by your MCP
    server and adjust `search_tool` if necessary.
    """

    def __init__(
        self,
        url: str,
        cloud_id: str | None,
        search_tool: str = "searchAtlassian",
        email: str | None = None,
        api_token: str | None = None,
    ):
        self.url = url
        self.cloud_id = cloud_id
        self.search_tool = search_tool
        self.headers: dict[str, str] = {}
        if email and api_token:
            encoded = base64.b64encode(f"{email}:{api_token}".encode()).decode()
            self.headers["Authorization"] = f"Basic {encoded}"

    async def _call(self, tool_name: str, arguments: dict) -> tuple[str, dict]:
        try:
            import httpx
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install MCP support: pip install -e '.[mcp]'") from exc

        async with AsyncExitStack() as stack:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=self.headers,
                    timeout=httpx.Timeout(30.0, read=300.0),
                    follow_redirects=True,
                )
            )
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(self.url, http_client=http_client)
            )
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                parts: list[str] = []
                for block in result.content:
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
                structured = getattr(result, "structuredContent", None) or {}
                return "\n".join(parts), structured

    async def list_tools_async(self) -> list[str]:
        try:
            import httpx
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install MCP support: pip install -e '.[mcp]'") from exc
        async with AsyncExitStack() as stack:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=self.headers,
                    timeout=httpx.Timeout(30.0, read=300.0),
                    follow_redirects=True,
                )
            )
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(self.url, http_client=http_client)
            )
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                return [tool.name for tool in result.tools]

    def list_tools(self) -> list[str]:
        return asyncio.run(self.list_tools_async())

    def search(self, query: str) -> ToolResult:
        args = {"query": query}
        if self.cloud_id:
            args["cloudId"] = self.cloud_id
        text, structured = asyncio.run(self._call(self.search_tool, args))
        content = text or json.dumps(structured, indent=2)
        return ToolResult(
            source=EvidenceSource.CONFLUENCE,
            category=EvidenceCategory.REFERENCE,
            summary=f"MCP search via {self.search_tool}",
            content=content,
            metadata={"query": query, "provider": "atlassian_rovo_mcp"},
        )
