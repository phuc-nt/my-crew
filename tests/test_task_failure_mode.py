"""The failure-mode vocabulary: a fixed enum every terminal stall maps into.

`event_kind` names the code path that fired; the failure mode names what went wrong
for the CEO, grouped the MAST way (spec / verification / system). The retro counts
the mode, so the mapping must be total over the terminal kinds, silent over the
rest, and every mode must carry a group and a label.
"""

from __future__ import annotations

import pytest

from my_crew.runtime.task_failure_mode import (
    FAILURE_MODE_GROUP,
    FAILURE_MODE_LABELS,
    FAILURE_MODES,
    GROUP_LABELS,
    failure_group_for,
    failure_mode_for,
)


@pytest.mark.parametrize("event_kind, mode", [
    ("cost_cap_exceeded", "cost_cap"),
    ("plan_hash_mismatch", "plan_mismatch"),
    ("review_rounds_exhausted", "verification_exhausted"),
    ("task_stalled_dead_step", "dead_step"),
    ("gave_up", "step_exhausted"),
])
def test_every_terminal_kind_maps_to_one_mode(event_kind, mode):
    assert failure_mode_for(event_kind) == mode


@pytest.mark.parametrize("event_kind", ["stuck", "step_failed", "task_stuck", "done", "", None])
def test_non_terminal_and_unknown_kinds_map_to_nothing(event_kind):
    """A ruling that puts the step back to pending is not a task failure yet;
    stamping it would count tasks that later finished."""
    assert failure_mode_for(event_kind) is None


def test_every_mode_has_a_group_and_a_label():
    for mode in FAILURE_MODES:
        assert failure_group_for(mode) in GROUP_LABELS, mode
        assert FAILURE_MODE_LABELS[mode].strip(), mode
    assert set(FAILURE_MODE_GROUP) == set(FAILURE_MODE_LABELS)


def test_the_three_mast_groups_are_all_reachable():
    """A taxonomy with an empty bucket is a bucket nobody will ever read against."""
    assert set(FAILURE_MODE_GROUP.values()) == {"spec", "verification", "system"}


def test_an_unknown_mode_has_no_group():
    assert failure_group_for("something_newer") is None
    assert failure_group_for("") is None
