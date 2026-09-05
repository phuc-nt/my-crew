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


def _response(reasoning_tokens=None, content="ok"):
    details = (
        SimpleNamespace(reasoning_tokens=reasoning_tokens)
        if reasoning_tokens is not None
        else None
    )
    msg = _Message()
    msg.content = content
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="stop")],
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


def test_the_retry_happens_at_most_once(monkeypatch, tmp_path):
    # Reasoning already off and still nothing: that is the model's answer, not a policy
    # problem — the caller's own empty-content handling applies, no second retry.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(
        monkeypatch, cl, responses=[_response(reasoning_tokens=5, content="")],
    )
    result = cl.complete([{"role": "user", "content": "x"}], role="sprint_low")
    assert result.content == ""
    assert len(seen) == 1


def test_an_empty_answer_without_reasoning_is_not_retried(monkeypatch, tmp_path):
    # No reasoning tokens ⇒ nothing was "spent on thinking"; an empty reply is a reply.
    cl = c.LlmClient(_settings(tmp_path))
    seen = _capture_requests(monkeypatch, cl, responses=[_response(content="")])
    cl.complete([{"role": "user", "content": "x"}], role="plan")
    assert len(seen) == 1


def test_thought_but_said_nothing_predicate_shapes():
    assert c._thought_but_said_nothing(_response(reasoning_tokens=3, content=""))
    assert not c._thought_but_said_nothing(_response(reasoning_tokens=3, content="hi"))
    assert not c._thought_but_said_nothing(_response(content=""))
    tool_msg = {"role": "assistant", "content": None,
                "tool_calls": [{"id": "1", "type": "function"}]}
    as_dict = {"choices": [SimpleNamespace(message=tool_msg)],
               "usage": {"completion_tokens_details": {"reasoning_tokens": 9}}}
    assert not c._thought_but_said_nothing(SimpleNamespace(**as_dict))


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
