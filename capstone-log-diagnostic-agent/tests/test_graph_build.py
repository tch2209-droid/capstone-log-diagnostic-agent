from pathlib import Path

from log_diagnostic_agent.config import Settings
from log_diagnostic_agent.langgraph_app import build_graph
from log_diagnostic_agent.toolkit import ToolKit


class BuildOnlyModel:
    def bind_tools(self, _tools):
        return self


def test_full_langgraph_compiles_without_credentials():
    data = Path(__file__).resolve().parents[1] / "data"
    settings = Settings(
        log_root=data,
        project_roots={"demo": data / "source"},
        use_pgvector=False,
    )
    graph = build_graph(settings, ToolKit.demo(data), BuildOnlyModel())
    assert {
        "triage",
        "supervisor",
        "execute_tool",
        "remember",
        "hypothesize",
        "branches",
        "critic",
        "evidence_gate",
        "human_review",
        "jira_ticket",
        "finalize",
    }.issubset(graph.nodes)
