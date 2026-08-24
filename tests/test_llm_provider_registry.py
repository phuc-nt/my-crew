"""v91: `provider::model` routing — registry resolution, per-provider client cache,
cross-provider chain fallback, and the error paths.

The failure this guards is silent misrouting. A chain entry is just a string, so a
prefix that resolves to the wrong endpoint (or to OpenRouter by accident) produces a
confusing upstream 404 rather than a config error, and the operator is left reading
provider dashboards. Every resolution rule below therefore either routes exactly or
raises with the provider name in the message.

Offline: the SDK constructor is replaced with a recorder, so no network and no key.
"""

from __future__ import annotations

import pytest

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.llm import client as c

_REGISTRY = {
    "deepseek": {"base_url": "https://api.deepseek.test/v1", "api_key_env": "DS_KEY"},
    "moonshot": {"base_url": "https://api.moonshot.test/v1", "api_key_env": "MS_KEY"},
}


class _Recorder:
    """Stands in for `OpenAI`, capturing construction args and every create() call."""

    built: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _Recorder.built.append(kwargs)
        outer = self

        class completions:
            @staticmethod
            def create(**call_kwargs):
                outer.calls.append(call_kwargs)
                raise RuntimeError("stop after routing")  # not retryable: propagates

        self.calls: list[dict] = []
        self.chat = type("chat", (), {"completions": completions})()


@pytest.fixture(autouse=True)
def _fake_sdk(monkeypatch):
    _Recorder.built = []
    monkeypatch.setattr(c, "OpenAI", _Recorder)


def _client(monkeypatch, **overrides):
    monkeypatch.setenv("DS_KEY", "ds-secret")
    monkeypatch.setenv("MS_KEY", "ms-secret")
    d = {"openrouter_api_key": "or-key", "openrouter_model": "org/fleet",
         "providers": _REGISTRY}
    d.update(overrides)
    return c.LlmClient(build_settings_from_dict(d))


class TestEntryParsing:
    def test_a_bare_model_id_stays_on_openrouter(self, monkeypatch):
        assert _client(monkeypatch)._resolve_entry("org/model") == ("openrouter", "org/model")

    def test_a_prefixed_entry_splits_into_provider_and_model(self, monkeypatch):
        cl = _client(monkeypatch)
        assert cl._resolve_entry("deepseek::deepseek-chat") == ("deepseek", "deepseek-chat")

    def test_only_the_first_separator_splits_so_a_model_may_contain_one(self, monkeypatch):
        """The prefix is routing; everything after it belongs to the upstream name."""
        cl = _client(monkeypatch)
        assert cl._resolve_entry("deepseek::a::b") == ("deepseek", "a::b")

    def test_an_openrouter_style_free_suffix_is_not_mistaken_for_a_prefix(self, monkeypatch):
        """A single `:` is ordinary in OpenRouter ids and must not route anywhere."""
        cl = _client(monkeypatch)
        assert cl._resolve_entry("org/model:free") == ("openrouter", "org/model:free")

    @pytest.mark.parametrize("entry", ["::model", "deepseek::"])
    def test_a_half_empty_entry_raises_instead_of_guessing(self, monkeypatch, entry):
        with pytest.raises(ValueError, match="malformed"):
            _client(monkeypatch)._resolve_entry(entry)


class TestClientConstruction:
    def test_a_bare_entry_builds_the_openrouter_client_exactly_as_before(self, monkeypatch):
        cl = _client(monkeypatch)
        with pytest.raises(RuntimeError, match="stop after routing"):
            cl._call_with_retry([{"role": "user", "content": "hi"}], "org/model")
        built = _Recorder.built[-1]
        assert built["base_url"] == c.OPENROUTER_BASE_URL
        assert built["api_key"] == "or-key"

    def test_a_prefixed_entry_uses_the_registry_base_url_and_that_provider_key(
        self, monkeypatch
    ):
        cl = _client(monkeypatch)
        with pytest.raises(RuntimeError, match="stop after routing"):
            cl._call_with_retry([{"role": "user", "content": "hi"}], "deepseek::deepseek-chat")
        built = _Recorder.built[-1]
        assert built["base_url"] == "https://api.deepseek.test/v1"
        assert built["api_key"] == "ds-secret"

    def test_the_model_id_sent_upstream_has_the_prefix_stripped(self, monkeypatch):
        """The prefix is our routing syntax; the vendor has never heard of it."""
        cl = _client(monkeypatch)
        client_obj = cl._client_for("deepseek")
        with pytest.raises(RuntimeError, match="stop after routing"):
            cl._call_with_retry([{"role": "user", "content": "hi"}], "deepseek::deepseek-chat")
        assert client_obj.calls[-1]["model"] == "deepseek-chat"

    def test_openrouter_attribution_headers_do_not_ride_to_other_vendors(self, monkeypatch):
        cl = _client(monkeypatch)
        or_client = cl._client_for("openrouter")
        ds_client = cl._client_for("deepseek")
        for entry in ("org/model", "deepseek::deepseek-chat"):
            with pytest.raises(RuntimeError, match="stop after routing"):
                cl._call_with_retry([{"role": "user", "content": "hi"}], entry)
        assert "HTTP-Referer" in or_client.calls[-1]["extra_headers"]
        assert ds_client.calls[-1]["extra_headers"] == {}

    def test_each_provider_gets_one_cached_client_not_one_per_call(self, monkeypatch):
        """Rebuilding per call would drop the SDK's connection pool on every fallback."""
        cl = _client(monkeypatch)
        first = cl._client_for("deepseek")
        assert cl._client_for("deepseek") is first
        assert cl._client_for("moonshot") is not first
        assert len(_Recorder.built) == 2

    def test_no_client_is_built_until_a_call_needs_one(self, monkeypatch):
        """Non-LLM code (guardrails, graph build) must run with no key configured."""
        _client(monkeypatch)
        assert _Recorder.built == []


class TestErrorPaths:
    def test_an_unknown_provider_names_itself_and_lists_what_is_declared(self, monkeypatch):
        cl = _client(monkeypatch)
        with pytest.raises(RuntimeError, match="unknown model provider 'deepsek'") as exc:
            cl._client_for("deepsek")
        assert "deepseek, moonshot" in str(exc.value)

    def test_an_unset_provider_key_names_the_provider_and_the_env_var(self, monkeypatch):
        """Env-name indirection means the config never says what to set — so the
        error has to say both halves or the operator cannot act on it."""
        cl = _client(monkeypatch)
        monkeypatch.delenv("DS_KEY")
        with pytest.raises(RuntimeError, match=r"provider 'deepseek' needs API key in \$DS_KEY"):
            cl._client_for("deepseek")

    def test_a_prefixed_entry_with_no_registry_at_all_still_errors_clearly(self, monkeypatch):
        cl = _client(monkeypatch, providers={})
        with pytest.raises(RuntimeError, match="none declared"):
            cl._client_for("deepseek")


class TestNoKeyMaterialEscapes:
    def test_the_registry_carries_env_var_names_never_key_values(self, monkeypatch):
        """`Settings` is passed around widely and lands in error paths and debug dumps.
        Holding only the env var NAME means none of those can expose a key even by
        accident — the key is read from the environment at client-build time and lives
        only inside the SDK object."""
        cl = _client(monkeypatch)
        flat = repr(cl._settings.providers)
        assert "DS_KEY" in flat
        assert "ds-secret" not in flat

    def test_the_recorded_request_carries_the_routing_entry_not_the_endpoint_or_key(
        self, monkeypatch, tmp_path
    ):
        """The step transcript records the chain so a cost report can attribute spend.
        `provider::model` is routing metadata; the base_url and key must not ride along."""
        events: list[dict] = []
        monkeypatch.setattr(c, "record_event", events.append)
        cl = _client(
            monkeypatch, model_chain=["deepseek::deepseek-chat"], data_dir=tmp_path
        )
        monkeypatch.setattr(
            cl, "_call_with_retry", lambda *_a, **_k: _FakeResponse("ok")
        )
        cl.complete([{"role": "user", "content": "hi"}])

        blob = repr(events)
        assert "deepseek::deepseek-chat" in blob
        assert "ds-secret" not in blob
        assert "api.deepseek.test" not in blob


class TestChainFallbackAcrossProviders:
    def test_a_failing_provider_entry_degrades_to_the_next_entry_on_openrouter(
        self, monkeypatch, tmp_path
    ):
        """The whole point of the registry: a cheap third-party primary can die and
        the step still completes on the fleet model, exactly like a same-provider
        chain does."""
        seen: list[str] = []

        def _fake_call(messages, model_name, **_kw):
            seen.append(model_name)
            if model_name.startswith("deepseek::"):
                raise c.APITimeoutError.__new__(c.APITimeoutError)  # retryable ⇒ advance
            return _FakeResponse("done")

        cl = _client(
            monkeypatch,
            model_chain=["deepseek::deepseek-chat", "org/fleet"],
            data_dir=tmp_path,
        )
        monkeypatch.setattr(cl, "_call_with_retry", _fake_call)
        result = cl.complete([{"role": "user", "content": "hi"}])

        assert seen == ["deepseek::deepseek-chat", "org/fleet"]
        assert result.content == "done"
        assert result.model == "org/fleet"
        # The recorded provenance keeps the FULL entry, prefix included — otherwise a
        # cost report cannot say which vendor was actually billed for the failed leg.
        assert result.fallback_from == ("deepseek::deepseek-chat",)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                      "cost": 0.001}
        msg = type("Msg", (), {"content": content})()
        self.choices = [type("Choice", (), {"message": msg})()]
