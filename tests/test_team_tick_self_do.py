"""`make_self_do_step`: the real seam behind the coordinator's self-do."""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.runtime.team_tick_self_do import make_self_do_step


def test_no_api_key_means_no_self_do_at_all():
    assert make_self_do_step(None, SimpleNamespace(openrouter_api_key="")) is None


def test_with_a_key_the_callable_runs_one_content_call(monkeypatch):
    seen = {}

    class _Result:
        content = "  kết quả  "
        cost_usd = 0.03

    class _FakeLlm:
        def __init__(self, settings):
            seen["settings"] = settings

        def complete(self, messages, **kw):
            seen["messages"] = messages
            seen["role"] = kw.get("role")
            return _Result()

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)
    settings = SimpleNamespace(openrouter_api_key="k")
    loaded = SimpleNamespace(soul="Tôi là điều phối", project="", memory="", skills=[])
    self_do = make_self_do_step(loaded, settings)
    step = SimpleNamespace(step_id="s1", title="viết bảng so sánh")

    out = self_do(SimpleNamespace(id="t1"), step, "BỐI CẢNH: abc")

    assert out == ("kết quả", 0.03)
    assert seen["settings"] is settings
    assert seen["role"] == "content"
    flat = "\n".join(str(m.get("content", m)) for m in seen["messages"])
    assert "viết bảng so sánh" in flat
    assert "BỐI CẢNH: abc" in flat


def test_empty_model_output_is_reported_as_not_attempted(monkeypatch):
    class _FakeLlm:
        def __init__(self, settings):
            pass

        def complete(self, messages, **kw):
            return SimpleNamespace(content="   ", cost_usd=0.0)

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)
    self_do = make_self_do_step(None, SimpleNamespace(openrouter_api_key="k"))

    assert self_do(SimpleNamespace(id="t1"), SimpleNamespace(step_id="s1", title="x"), "") is None
