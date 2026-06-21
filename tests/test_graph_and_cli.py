"""Graph build + run (no network) and CLI arg handling."""

from __future__ import annotations

from src.agent.checkpoint import get_checkpointer
from src.agent.graph import build_graph
from src.entrypoints.cli import main as cli_main
from src.entrypoints.cron import main as cron_main
from src.llm.client import LlmResult


class _FakeClient:
    """Stand-in LLM client: echoes input, no network."""

    def complete(self, messages, *, model=None):
        return LlmResult(
            content="echo: " + messages[0]["content"],
            model="fake",
            prompt_tokens=1,
            completion_tokens=2,
            cost_usd=0.0001,
        )


def test_graph_compiles_without_network():
    graph = build_graph()
    assert graph is not None


def test_graph_runs_end_to_end_with_fake_client(tmp_path):
    cp = get_checkpointer(tmp_path / "checkpoints.db")
    graph = build_graph(cp, client=_FakeClient())
    out = graph.invoke(
        {"user_input": "hello", "llm_response": "", "cost_usd": None},
        config={"configurable": {"thread_id": "t"}},
    )
    assert out["llm_response"] == "echo: hello"
    assert out["cost_usd"] == 0.0001


def test_checkpointer_creates_db(tmp_path):
    db = tmp_path / "checkpoints.db"
    get_checkpointer(db)
    assert db.exists()


def test_cli_no_args_returns_usage_code():
    assert cli_main([]) == 2


def test_cli_no_key_returns_one(monkeypatch):
    # Ensure no key is visible regardless of the developer's real env.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    assert cli_main(["hello"]) == 1
    settings_mod.get_settings.cache_clear()


def test_cron_stub_runs():
    assert cron_main() == 0
