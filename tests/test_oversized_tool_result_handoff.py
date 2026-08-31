"""A huge tool result is stashed to disk, not poured into every following round.

`thin_tool_loop` appends each tool result to `messages`, and `messages` is re-sent on
every subsequent round. So one uncapped result (`history_search`, `openalex`, the issue
readers have no cap of their own) costs its own size MULTIPLIED by the rounds after it.

The fix must hold two things at once, which is what most of these tests pin:
  - the prompt gets bounded text that ANNOUNCES it is partial (a silent cut makes the
    model conclude from a truncated list as if it were whole);
  - the full text survives on disk, addressable, so nothing has to be re-fetched.
"""

from __future__ import annotations

import pytest

import my_crew.runtime_backends.thin_tool_loop as loop_mod
from my_crew.runtime.tool_result_stash import (
    STASH_PREVIEW_CHARS,
    TOOL_RESULT_STASH_CHARS,
    stash_if_oversized,
    tool_results_dir,
)
from my_crew.runtime_backends.tool_call_context import tool_call_context
from my_crew.runtime_backends.typed_tool_specs import build_typed_specs


@pytest.fixture
def stash_root(monkeypatch, tmp_path):
    """Point the shared team-tasks root at a tmp dir and hand back the stash dir."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return lambda task_id: tool_results_dir(tmp_path, task_id)


def _big(n: int) -> str:
    return "x" * n


# --- the threshold ---------------------------------------------------------------------


def test_a_result_under_the_threshold_is_passed_through_verbatim(stash_root):
    text = _big(TOOL_RESULT_STASH_CHARS - 1)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        assert stash_if_oversized(text, "history_search") == text


def test_a_result_exactly_at_the_threshold_is_left_alone(stash_root):
    """The cap is a ceiling, not a trigger — the boundary value must still be verbatim,
    or the "under the cap is untouched" contract is off by one."""
    text = _big(TOOL_RESULT_STASH_CHARS)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        assert stash_if_oversized(text, "history_search") == text


def test_nothing_is_written_for_a_result_that_fits(stash_root):
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        stash_if_oversized(_big(100), "history_search")
    assert not stash_root("t1").exists()


# --- what the model sees ---------------------------------------------------------------


def test_an_oversized_result_comes_back_bounded(stash_root):
    text = _big(TOOL_RESULT_STASH_CHARS * 5)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        out = stash_if_oversized(text, "history_search")

    assert len(out) < len(text)
    assert len(out) < TOOL_RESULT_STASH_CHARS


def test_the_placeholder_states_the_true_size_and_where_the_rest_went(stash_root):
    text = "ĐẦU" + _big(TOOL_RESULT_STASH_CHARS * 2)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        out = stash_if_oversized(text, "history_search")

    assert str(len(text)) in out           # the real size, not the shown size
    assert "tool-results/" in out          # where the full text is
    assert out.startswith("ĐẦU")           # the head is real content, not a banner


def test_the_preview_keeps_the_head_not_the_tail(stash_root):
    """A search result's most relevant rows come first; previewing the tail would show
    the model the least useful part of what it asked for."""
    text = "MỞ ĐẦU QUAN TRỌNG " + _big(TOOL_RESULT_STASH_CHARS * 2) + " KẾT THÚC"
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        out = stash_if_oversized(text, "history_search")

    assert "MỞ ĐẦU QUAN TRỌNG" in out
    assert "KẾT THÚC" not in out


def test_the_preview_is_bounded_by_its_own_constant(stash_root):
    """Measured on the preview segment alone — the footer that follows it carries its own
    text and must not be counted as part of the shown content."""
    text = _big(TOOL_RESULT_STASH_CHARS * 4)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        out = stash_if_oversized(text, "history_search")

    preview = out.split("\n…[")[0]
    assert preview == _big(STASH_PREVIEW_CHARS)
    assert str(STASH_PREVIEW_CHARS) in out  # and it says how much it showed


# --- what survives on disk -------------------------------------------------------------


def test_the_full_text_is_recoverable_from_the_artifact(stash_root):
    text = "ĐẦU " + _big(TOOL_RESULT_STASH_CHARS * 2) + " CUỐI"
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=3):
        stash_if_oversized(text, "history_search")

    files = list(stash_root("t1").glob("*.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == text


def test_the_artifact_named_in_the_placeholder_is_the_one_written(stash_root):
    """The pointer is worthless if it names a file that is not there."""
    text = _big(TOOL_RESULT_STASH_CHARS * 2)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=2):
        out = stash_if_oversized(text, "history_search")

    named = out.split("tool-results/")[1].split(".txt")[0]
    assert (stash_root("t1") / f"{named}.txt").exists()


def test_two_calls_to_one_tool_in_a_round_do_not_overwrite_each_other(stash_root):
    """One round may call the same tool twice. Sharing a filename would silently destroy
    the first result — exactly the evidence the stash exists to keep."""
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        stash_if_oversized("MỘT" + _big(TOOL_RESULT_STASH_CHARS * 2), "history_search", 0)
        stash_if_oversized("HAI" + _big(TOOL_RESULT_STASH_CHARS * 2), "history_search", 1)

    bodies = sorted(p.read_text(encoding="utf-8")[:3] for p in stash_root("t1").glob("*.txt"))
    assert bodies == ["HAI", "MỘT"]


def test_different_rounds_get_different_artifacts(stash_root):
    text = _big(TOOL_RESULT_STASH_CHARS * 2)
    for round_no in (0, 1):
        with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=round_no):
            stash_if_oversized(text, "history_search")

    assert len(list(stash_root("t1").glob("*.txt"))) == 2


def test_a_secret_in_a_stashed_result_is_scrubbed_on_disk(stash_root):
    """The stash is a file that outlives the run — it must not become the one place a
    leaked key is stored in the clear."""
    text = "token sk-abcdefghijklmnopqrstuvwxyz012345\n" + _big(TOOL_RESULT_STASH_CHARS * 2)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        stash_if_oversized(text, "history_search")

    on_disk = next(stash_root("t1").glob("*.txt")).read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in on_disk


# --- degrading without an identity or a disk -------------------------------------------


def test_without_a_task_id_the_text_is_still_bounded(stash_root):
    """A CLI run or a bare toolset has no task to write under. Bounding the context is the
    half that must work everywhere; keeping the data is the half that can be missed."""
    text = _big(TOOL_RESULT_STASH_CHARS * 3)
    out = stash_if_oversized(text, "history_search")

    assert len(out) < TOOL_RESULT_STASH_CHARS
    assert str(len(text)) in out


def test_an_unwritable_stash_says_so_instead_of_pointing_at_nothing(stash_root, monkeypatch):
    """A placeholder claiming an artifact that was never written would send a later reader
    hunting for a file that does not exist."""
    def _boom(*a, **k):
        raise OSError("đĩa đầy")

    monkeypatch.setattr("pathlib.Path.write_text", _boom)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        out = stash_if_oversized(_big(TOOL_RESULT_STASH_CHARS * 2), "history_search")

    assert "tool-results/" not in out
    assert "KHÔNG lưu được" in out


def test_a_write_failure_never_breaks_the_step(stash_root, monkeypatch):
    def _boom(*a, **k):
        raise OSError("đĩa đầy")

    monkeypatch.setattr("pathlib.Path.write_text", _boom)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        out = stash_if_oversized(_big(TOOL_RESULT_STASH_CHARS * 2), "history_search")

    assert out  # a placeholder, not an exception


def test_a_hostile_task_id_cannot_escape_the_artifacts_root(stash_root):
    """`task_id` reaches the path from stored task state; a traversal attempt must fail
    the write, not walk out of the confined dir."""
    with tool_call_context(agent_id="a", task_id="../../etc", step_id="s1", iteration=0):
        out = stash_if_oversized(_big(TOOL_RESULT_STASH_CHARS * 2), "history_search")

    assert "KHÔNG lưu được" in out


# --- the loop actually uses it ---------------------------------------------------------


def _run_one_round(monkeypatch, tool_output: str):
    """Drive `_execute_call` the way the loop does, through a real ToolSpec."""
    tools_map = {"history_search": lambda args: tool_output}
    by_name = {s.name: s for s in build_typed_specs(tools_map)}
    call = {"id": "c1", "function": {"name": next(iter(by_name)), "arguments": "{}"}}
    return loop_mod._execute_call(call, by_name, tools_map, 0)


def test_the_loop_puts_the_placeholder_not_the_payload_into_messages(stash_root, monkeypatch):
    """The point of the whole phase: what lands in `messages` is what gets re-sent every
    later round, so THAT is what must be bounded."""
    text = _big(TOOL_RESULT_STASH_CHARS * 3)
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        result = _run_one_round(monkeypatch, text)

    assert len(result["content"]) < TOOL_RESULT_STASH_CHARS
    assert str(len(text)) in result["content"]


def test_a_normal_sized_tool_result_reaches_the_loop_unchanged(stash_root, monkeypatch):
    with tool_call_context(agent_id="a", task_id="t1", step_id="s1", iteration=0):
        result = _run_one_round(monkeypatch, "kết quả bình thường")

    assert result["content"] == "kết quả bình thường"
