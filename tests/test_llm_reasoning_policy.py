"""Per-role reasoning level: a thinking model must not think on a four-sentence step.

Measured 2026-09-05 on journey J1 with the fleet default `~deepseek/deepseek-v4-flash-latest`
(OpenRouter registry: reasoning `default_enabled: true`, `default_effort: high`): the sprint
step for a four-sentence company intro spent 10,929 completion tokens on 227 visible
characters and took 6m16s; a clarify note spent 8,345 tokens and 3m34s; the outside-caller
journey then timed out at 300s on a brief the same fleet had finished in 66s. The policy
sends OpenRouter's `reasoning` body key per role so judgement calls keep the model's default
and short deliverables / mechanical calls do not pay for thinking.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.config.settings import (
    DEFAULT_ROLE_REASONING,
    MODEL_ROLES,
    REASONING_LEVELS,
)
from my_crew.llm import client as c
from my_crew.llm.cost import extract_usage


def _settings(tmp_path, **over):
    base = {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": True}
    base.update(over)
    return build_settings_from_dict(base)


# ----------------------------------------------------------------------------- policy


def test_every_role_has_a_built_in_level_and_it_is_a_known_one():
    for role in MODEL_ROLES:
        assert DEFAULT_ROLE_REASONING[role] in REASONING_LEVELS


def test_the_built_in_policy_keeps_thinking_for_judgements_and_drops_it_for_short_work():
    # plan/review are judgements over structure and acceptance — thinking earns its cost.
    assert DEFAULT_ROLE_REASONING["plan"] == "model"
    assert DEFAULT_ROLE_REASONING["review"] == "model"
    # util and aggregate are judgements over small inputs: the scorecard had util at
    # 0.89 thinking / 0.61 not (slot extraction 0/3), aggregate 1.00 / 0.67.
    assert DEFAULT_ROLE_REASONING["util"] == "model"
    assert DEFAULT_ROLE_REASONING["aggregate"] == "model"
    # The deliverable roles are OFF, not merely bounded: at effort=low the fleet model
    # returned an EMPTY answer 2 times in 5 (118 and 1,972 reasoning tokens, no
    # content), while off was 3/3 clean and scored 1.00 on the scorecard 2–3× faster.
    for role in ("content", "advisor", "sprint_low"):
        assert DEFAULT_ROLE_REASONING[role] == "off", role


def test_reasoning_for_role_falls_back_to_the_built_in_default(tmp_path):
    s = _settings(tmp_path)
    assert s.role_reasoning == ()
    for role in MODEL_ROLES:
        assert s.reasoning_for_role(role) == DEFAULT_ROLE_REASONING[role]


def test_an_absent_or_unknown_role_sends_nothing(tmp_path):
    s = _settings(tmp_path)
    assert s.reasoning_for_role(None) == "model"
    assert s.reasoning_for_role("not-a-role") == "model"


def test_an_override_replaces_only_its_own_role(tmp_path):
    s = _settings(tmp_path, role_reasoning="content=model, util=low")
    assert s.reasoning_for_role("content") == "model"
    assert s.reasoning_for_role("util") == "low"
    assert s.reasoning_for_role("sprint_low") == DEFAULT_ROLE_REASONING["sprint_low"]


def test_the_yaml_mapping_form_is_accepted(tmp_path):
    s = _settings(tmp_path, role_reasoning={"review": "off"})
    assert s.role_reasoning == (("review", "off"),)


@pytest.mark.parametrize(
    "bad, fragment",
    [
        ("contnet=low", "unknown role_reasoning key"),
        ("content=turbo", "valid levels"),
        ("content=low,content=off", "twice"),
        ("content", "must be 'role=level'"),
    ],
)
def test_a_typo_raises_instead_of_silently_meaning_the_default(tmp_path, bad, fragment):
    with pytest.raises(ValueError, match=fragment):
        _settings(tmp_path, role_reasoning=bad)


# ------------------------------------------------------------------------- wire shape


def test_reasoning_body_shapes():
    assert c._reasoning_body("model") is None
    assert c._reasoning_body("off") == {"enabled": False}
    assert c._reasoning_body("low") == {"effort": "low"}


class _Message:
    """The SDK message shape both client paths touch: `.content` on the text path,
    `model_dump()` on the tools path."""

    content = "ok"
    tool_calls = None

    def model_dump(self):
        return {"role": "assistant", "content": self.content}


def _response(reasoning_tokens=None, content="ok", finish_reason="stop"):
    details = (
        SimpleNamespace(reasoning_tokens=reasoning_tokens)
        if reasoning_tokens is not None
        else None
    )
    msg = _Message()
    msg.content = content
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=20, total_tokens=30,
            completion_tokens_details=details,
        ),
    )


def _capture_requests(monkeypatch, cl, reasoning_tokens=None, responses=None):
    """Replace the wire call; `responses` (a list) is consumed in order, the last one
    repeating, so a test can script "empty first, then an answer"."""
    seen: list[dict] = []
    queue = list(responses or [])

    def _fake(client, *, progress, **request):
        seen.append(request)
        if queue:
            return queue.pop(0) if len(queue) > 1 else queue[0]
        return _response(reasoning_tokens)

    monkeypatch.setattr(c, "_stream_completion", _fake)
    monkeypatch.setattr(cl, "_client_for", lambda _p: None)
    return seen


def test_a_bounded_role_sends_the_reasoning_body(monkeypatch, tmp_path):
    cl = c.LlmClient(_settings(tmp_path, role_reasoning="content=minimal"))
    seen = _capture_requests(monkeypatch, cl)
    cl.complete([{"role": "user", "content": "x"}], role="content")
    cl.complete([{"role": "user", "content": "x"}], role="sprint_low")
    assert seen[0]["extra_body"] == {"reasoning": {"effort": "minimal"}}
    assert seen[1]["extra_body"] == {"reasoning": {"enabled": False}}


def test_a_model_default_role_sends_no_reasoning_key(monkeypatch, tmp_path):
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(monkeypatch, cl)
    cl.complete([{"role": "user", "content": "x"}], role="plan")
    cl.complete([{"role": "user", "content": "x"}])
    assert "extra_body" not in seen[0]
    assert "extra_body" not in seen[1]


def test_the_tools_path_carries_the_same_policy(monkeypatch, tmp_path):
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(monkeypatch, cl)
    tool = {"type": "function", "function": {"name": "step", "parameters": {}}}
    cl.complete_with_tools([{"role": "user", "content": "x"}], [tool], role="content")
    assert seen[0]["tools"] == [tool]
    assert seen[0]["extra_body"] == {"reasoning": {"enabled": False}}


def test_the_reasoning_key_rides_only_on_openrouter_calls(monkeypatch, tmp_path):
    # Another provider's endpoint may reject a body key it does not know, so the policy
    # stays on the OpenRouter side of a `provider::model` chain — same rule as the
    # attribution headers.
    s = _settings(
        tmp_path,
        providers="alt=https://alt.example/v1|ALT_KEY",
        openrouter_model="alt::other-lab/model",
    )
    cl = c.LlmClient(s)
    seen = _capture_requests(monkeypatch, cl)
    cl.complete([{"role": "user", "content": "x"}], role="content")
    assert seen[0]["model"] == "other-lab/model"
    assert "extra_body" not in seen[0]


# ------------------------------------------------------------- thought but said nothing


def test_an_empty_answer_spent_on_thinking_is_retried_once_with_the_same_request(
    monkeypatch, tmp_path,
):
    # Measured shape: completion == reasoning tokens, content empty, finish_reason=stop.
    # The empty answer is stochastic — the same request re-asked answers — while
    # re-asking with reasoning OFF was measured to return prose for structured
    # prompts, so the retry must change nothing about the request.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(
        monkeypatch, cl,
        responses=[_response(reasoning_tokens=1972, content=""), _response(content="ok")],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="plan")
    assert result.content == "ok"
    assert len(seen) == 2
    assert "extra_body" not in seen[0]  # plan keeps the model default...
    assert seen[1] == seen[0]  # ...and so does the retry


def test_a_second_empty_answer_is_returned_not_retried_again(monkeypatch, tmp_path):
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(
        monkeypatch, cl,
        responses=[_response(reasoning_tokens=1972, content=""),
                   _response(reasoning_tokens=300, content="")],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="plan")
    assert result.content == ""
    assert len(seen) == 2


def test_the_retry_happens_at_most_once_even_with_thinking_off(monkeypatch, tmp_path):
    # Thinking off and still nothing: an empty answer is the same stochastic non-answer
    # whatever the reasoning policy, so it gets the one identical retry — and when that
    # one is empty too, the caller's own empty-content handling applies, no third ask.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(
        monkeypatch, cl,
        responses=[_response(reasoning_tokens=5, content=""), _response(content="")],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="sprint_low")
    assert result.content == ""
    assert len(seen) == 2
    assert seen[0] == seen[1]


def test_an_empty_answer_without_reasoning_is_retried_once(monkeypatch, tmp_path):
    # Measured on the review self-check (deepseek-v4-flash, 1/12 calls): 0 reasoning
    # tokens, 0 content, finish_reason=stop, 1.5 s — the provider returned nothing at
    # all. A billed non-answer with the same remedy as the thinking-only one.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(
        monkeypatch, cl, responses=[_response(content=""), _response(content="ok")],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="plan")
    assert result.content == "ok"
    assert len(seen) == 2
    assert seen[0] == seen[1]


def test_thinking_that_hit_the_answer_cap_is_not_retried(monkeypatch, tmp_path):
    # Measured: ~16k reasoning tokens, no content, finish_reason=length, 5–11 min. The
    # same request re-asked hit the cap again 5/6 times, so a repeat is ten more
    # minutes for a 1/6 chance — the empty, truncated answer goes back to the caller.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(
        monkeypatch, cl,
        responses=[_response(reasoning_tokens=16145, content="", finish_reason="length"),
                   _response(content="never asked")],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="review")
    assert result.content == ""
    assert result.finish_reason == "length"
    assert len(seen) == 1


def test_a_cap_hit_with_content_is_a_normal_truncated_answer(monkeypatch, tmp_path):
    # Content that ran into the cap is a long answer, not an empty one: no retry.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(
        monkeypatch, cl,
        responses=[_response(reasoning_tokens=702, content="x" * 50, finish_reason="length")],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="review")
    assert result.content == "x" * 50
    assert len(seen) == 1


def test_said_nothing_predicate_shapes():
    assert c._said_nothing(_response(reasoning_tokens=3, content=""))
    assert c._said_nothing(_response(content=""))
    assert c._said_nothing(_response(content="   "))
    assert not c._said_nothing(_response(reasoning_tokens=3, content="hi"))
    tool_msg = {"role": "assistant", "content": None,
                "tool_calls": [{"id": "1", "type": "function"}]}
    as_dict = {"choices": [SimpleNamespace(message=tool_msg)],
               "usage": {"completion_tokens_details": {"reasoning_tokens": 9}}}
    assert not c._said_nothing(SimpleNamespace(**as_dict))
    assert not c._said_nothing(SimpleNamespace(choices=[]))


def test_answer_cap_predicate_shapes():
    assert c._hit_the_answer_cap(_response(content="", finish_reason="length"))
    assert not c._hit_the_answer_cap(_response(content=""))
    assert not c._hit_the_answer_cap(SimpleNamespace(choices=[]))


# --------------------------------------------------------------------------- accounting


def test_usage_reads_reasoning_tokens_and_tolerates_their_absence():
    assert extract_usage(_response(reasoning_tokens=301)).reasoning_tokens == 301
    assert extract_usage(_response()).reasoning_tokens == 0
    as_dict = {"usage": {"prompt_tokens": 1, "completion_tokens": 2,
                         "completion_tokens_details": {"reasoning_tokens": 7}}}
    assert extract_usage(as_dict).reasoning_tokens == 7


def test_the_result_surfaces_reasoning_tokens(monkeypatch, tmp_path):
    cl = c.LlmClient(_settings(tmp_path))
    _capture_requests(monkeypatch, cl, reasoning_tokens=301)
    result = cl.complete([{"role": "user", "content": "x"}], role="content")
    assert result.reasoning_tokens == 301
    assert result.completion_tokens == 20


def test_every_request_carries_the_completion_cap(monkeypatch, tmp_path):
    """A degenerate stream (one decompose repeated `"needs_web":false,` for 903 s) is
    bounded by `max_tokens`, on the text path and the tools path alike."""
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(monkeypatch, cl)
    cl.complete([{"role": "user", "content": "x"}], role="plan")
    cl.complete_with_tools([{"role": "user", "content": "x"}], tools=[], role="content")
    assert seen[0]["max_tokens"] == c._MAX_COMPLETION_TOKENS
    assert seen[1]["max_tokens"] == c._MAX_COMPLETION_TOKENS
    assert seen[1]["tools"] == []
    assert c._MAX_COMPLETION_TOKENS >= 16000  # above the longest honest answer measured


def test_a_length_cut_stream_returns_the_partial_body_instead_of_raising(monkeypatch):
    # openai 2.x's stream assembler raises LengthFinishReasonError on finish_reason
    # "length" (it assumes structured parsing). The cap in `_MAX_COMPLETION_TOKENS`
    # makes that reason reachable; `LlmResult.truncated` and the "answer shorter"
    # retries need the partial body, not an exception.
    from openai import LengthFinishReasonError

    cut = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="partial…", tool_calls=None),
                                 finish_reason="length")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=16384, total_tokens=16385,
                              completion_tokens_details=None),
    )

    class _State:
        def __init__(self):
            self.chunks = 0

        def handle_chunk(self, chunk):
            self.chunks += 1

        def get_final_completion(self):
            raise LengthFinishReasonError(completion=cut)

    monkeypatch.setattr(c, "ChatCompletionStreamState", _State)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_kw: iter(["chunk-1", "chunk-2"]),
    )))
    got = c._stream_completion(fake_client, progress=c._Progress(), model="m", messages=[])
    assert got is cut
    assert got.choices[0].finish_reason == "length"


def test_the_serving_provider_is_carried_from_stream_chunks_to_the_result(monkeypatch):
    # OpenRouter routes one alias across several upstreams and stamps `provider` on
    # every chunk; the SDK's assembler drops it. A degraded episode was measured
    # per-upstream, so the result and transcript must say who served the call.
    final = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None),
                                 finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3,
                              completion_tokens_details=None),
    )

    class _State:
        def handle_chunk(self, chunk):
            pass

        def get_final_completion(self):
            return final

    monkeypatch.setattr(c, "ChatCompletionStreamState", _State)
    chunks = [SimpleNamespace(provider="OpenInference"), SimpleNamespace(provider=None),
              SimpleNamespace(model_extra={})]
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_kw: iter(chunks),
    )))
    got = c._stream_completion(fake_client, progress=c._Progress(), model="m", messages=[])
    assert got is final
    assert c._serving_provider(got) == "OpenInference"


def test_a_length_cut_stream_still_records_the_provider(monkeypatch):
    from openai import LengthFinishReasonError

    cut = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="p", tool_calls=None),
                                 finish_reason="length")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3,
                              completion_tokens_details=None),
    )

    class _State:
        def handle_chunk(self, chunk):
            pass

        def get_final_completion(self):
            raise LengthFinishReasonError(completion=cut)

    monkeypatch.setattr(c, "ChatCompletionStreamState", _State)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_kw: iter([SimpleNamespace(provider="DeepSeek")]),
    )))
    got = c._stream_completion(fake_client, progress=c._Progress(), model="m", messages=[])
    assert c._serving_provider(got) == "DeepSeek"


def test_serving_provider_predicate_shapes():
    assert c._serving_provider(SimpleNamespace(provider="DeepSeek")) == "DeepSeek"
    assert c._serving_provider(SimpleNamespace(provider=None)) == ""
    assert c._serving_provider(SimpleNamespace()) == ""
    assert c._serving_provider({"provider": "Fireworks"}) == "Fireworks"
    assert c._serving_provider({}) == ""


def test_the_result_and_the_transcript_event_name_the_provider(monkeypatch, tmp_path):
    cl = c.LlmClient(_settings(tmp_path))
    served = _response()
    served.provider = "OpenInference"
    _capture_requests(monkeypatch, cl, responses=[served])
    events: list[dict] = []
    monkeypatch.setattr(c, "record_event", events.append)
    result = cl.complete([{"role": "user", "content": "x"}], role="content")
    assert result.provider == "OpenInference"
    responses = [e for e in events if e.get("t") == "llm_response"]
    assert responses and responses[-1]["provider"] == "OpenInference"


def test_a_result_without_a_provider_field_reports_an_empty_provider(monkeypatch, tmp_path):
    cl = c.LlmClient(_settings(tmp_path))
    _capture_requests(monkeypatch, cl)
    result = cl.complete([{"role": "user", "content": "x"}], role="content")
    assert result.provider == ""


def test_the_empty_answer_warning_names_the_provider(monkeypatch, tmp_path, caplog):
    cl = c.LlmClient(_settings(tmp_path, role_reasoning="sprint_low=off"))
    empty = _response(content="")
    empty.provider = "OpenInference"
    _capture_requests(monkeypatch, cl, responses=[empty, _response()])
    with caplog.at_level("WARNING", logger=c.logger.name):
        cl.complete([{"role": "user", "content": "x"}], role="sprint_low")
    assert any("(via OpenInference)" in r.getMessage() for r in caplog.records)


def _midstream_error(message: str):
    import httpx
    from openai import APIError

    req = httpx.Request("POST", "https://openrouter.test/v1/chat/completions")
    return APIError(message, req, body=None)


def _status_error(code: int):
    import httpx
    from openai import APIStatusError

    req = httpx.Request("POST", "https://openrouter.test/v1/chat/completions")
    return APIStatusError(f"http {code}", response=httpx.Response(code, request=req),
                          body=None)


def _capture_with_failures(monkeypatch, cl, script):
    """`script` is consumed per call: an exception instance is raised, anything else
    is returned as the response."""
    seen: list[dict] = []
    queue = list(script)

    def _fake(client, *, progress, **request):
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(c, "_stream_completion", _fake)
    monkeypatch.setattr(cl, "_client_for", lambda _p: None)
    monkeypatch.setattr(c.time, "sleep", lambda _s: None)
    return seen


def test_an_upstream_error_sent_mid_stream_is_retried(monkeypatch, tmp_path):
    # OpenRouter accepted the request, then one upstream failed while streaming
    # ("Upstream error from DigitalOcean: stream failed"): no HTTP status, plain
    # APIError. The alias is routed per call, so the retry is worth one more try.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_with_failures(
        monkeypatch, cl,
        [_midstream_error("Upstream error from DigitalOcean: stream failed"), _response()],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="content")
    assert result.content == "ok"
    assert len(seen) == 2


def test_a_bad_request_status_still_propagates_without_a_retry(monkeypatch, tmp_path):
    from openai import APIStatusError

    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_with_failures(monkeypatch, cl, [_status_error(400), _response()])
    with pytest.raises(APIStatusError):
        cl.complete([{"role": "user", "content": "x"}], role="content")
    assert len(seen) == 1


def test_transient_predicate_shapes():
    import httpx
    from openai import RateLimitError

    req = httpx.Request("POST", "https://openrouter.test/v1/chat/completions")
    assert c._is_transient(_midstream_error("stream failed"))
    assert c._is_transient(RateLimitError("429", response=httpx.Response(429, request=req),
                                          body=None))
    assert not c._is_transient(_status_error(400))
    assert not c._is_transient(_status_error(500))
