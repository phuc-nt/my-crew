"""Graph build + run (no network) and CLI arg handling."""

from __future__ import annotations

from my_crew.agent.checkpoint import get_checkpointer
from my_crew.agent.graph import build_graph
from my_crew.entrypoints.cli import main as cli_main
from my_crew.llm.client import LlmResult


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


def test_graph_runs_end_to_end_with_fake_client(tmp_path, settings_factory):
    cp = get_checkpointer(settings_factory())  # data_dir = tmp_path
    graph = build_graph(cp, client=_FakeClient())
    out = graph.invoke(
        {"user_input": "hello", "llm_response": "", "cost_usd": None},
        config={"configurable": {"thread_id": "t"}},
    )
    assert out["llm_response"] == "echo: hello"
    assert out["cost_usd"] == 0.0001


def test_checkpointer_creates_db(tmp_path, settings_factory):
    get_checkpointer(settings_factory())  # data_dir = tmp_path
    assert (tmp_path / "checkpoints.db").exists()


def test_cli_no_args_returns_usage_code():
    assert cli_main([]) == 2


def test_cli_no_key_returns_one(monkeypatch, tmp_path):
    # Ensure no key is visible regardless of the developer's real .env.
    # Point settings at an empty tmp dir so load_dotenv finds no .env to reload.
    from my_crew.config import settings as settings_mod

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Also clear stakeholder/external channel vars so a CI runner that exports a
    # mismatched pair can't make config build error here.
    monkeypatch.delenv("SLACK_STAKEHOLDER_CHANNEL", raising=False)
    monkeypatch.delenv("SLACK_EXTERNAL_CHANNELS", raising=False)
    monkeypatch.setattr(settings_mod, "REPO_ROOT", tmp_path)
    # The profile loader load_dotenv's the real .env; block it so the deleted key
    # stays absent and _require_key returns 1.
    monkeypatch.setattr("my_crew.profile.loader.load_dotenv", lambda *a, **k: None)
    assert cli_main(["hello"]) == 1


# cron is no longer a stub (Slice 3) — covered by test_sprint_and_report_kind.py
# (test_cron_no_key_returns_one), which avoids hitting the network.
