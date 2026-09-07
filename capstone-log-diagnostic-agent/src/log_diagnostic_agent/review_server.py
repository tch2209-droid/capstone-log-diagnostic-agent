from __future__ import annotations

import argparse
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Settings
from .review_delivery import build_review_delivery_graph
from .toolkit import incident_rag_from_settings
from .tools.jira import jira_provider_from_settings


def main() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        load_dotenv = None

    parser = argparse.ArgumentParser(description="Serve the SignalDesk review handoff")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if load_dotenv:
        load_dotenv(root / ".env")
    token = os.getenv("SIGNALDESK_REVIEW_API_TOKEN", "")
    if not token:
        raise SystemExit("SIGNALDESK_REVIEW_API_TOKEN is required")
    settings = Settings.from_env(root)
    rag_store = incident_rag_from_settings(settings)
    setup = getattr(rag_store, "setup", None)
    if setup:
        setup()
    graph = build_review_delivery_graph(
        jira_provider_from_settings(settings), rag_store
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/review-decisions":
                self.send_error(404)
                return
            supplied = self.headers.get("authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {token}"):
                self.send_error(401)
                return
            try:
                length = int(self.headers.get("content-length", "0"))
                if length <= 0 or length > 2_000_000:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                result = graph.invoke(body)
                payload = json.dumps(
                    {
                        "jiraTickets": result.get("jira_tickets", []),
                        "memoryAdmission": result.get("memory_admission"),
                    }
                ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                payload = json.dumps({"error": str(exc)}).encode()
                self.send_response(400)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"SignalDesk review handoff listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
