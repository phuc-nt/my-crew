"""`--profile <id>` before a subcommand must route to that subcommand.

Regression: the CLI checked `args[0] == "report"` for dispatch, but `--profile x
report ...` makes `args[0] == "--profile"`, so the invocation fell through to the
hello path and sent the raw argv to the LLM as a prompt. `_strip_flag_value` removes
the flag+value so dispatch sees a clean subcommand.
"""

from __future__ import annotations

from my_crew.entrypoints.cli import _strip_flag_value


def test_strip_profile_before_subcommand():
    assert _strip_flag_value(["--profile", "x", "report", "--daily"], "--profile") == [
        "report", "--daily"
    ]


def test_strip_profile_absent_is_unchanged():
    assert _strip_flag_value(["report", "--daily"], "--profile") == ["report", "--daily"]


def test_strip_profile_trailing_without_value():
    # Defensive: a dangling `--profile` with no value still gets removed (no IndexError).
    assert _strip_flag_value(["report", "--profile"], "--profile") == ["report"]


def test_strip_profile_in_the_middle():
    assert _strip_flag_value(["audit", "--profile", "hr"], "--profile") == ["audit"]
