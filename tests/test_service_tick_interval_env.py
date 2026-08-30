"""`MY_CREW_TICK_INTERVAL_S` — the operations knob that paces the daemon loop.

A full-flow test driving a real `serve` process cannot wait the production minute per
tick. The knob exists for that, so the parsing has to hold the line the deployment
relies on: a bad value degrades to the default instead of leaving the CEO without a
dispatch engine.
"""

from __future__ import annotations

import pytest

from my_crew.runtime.service import _TICK_INTERVAL_S, resolve_tick_interval


def test_unset_env_keeps_the_production_default():
    assert resolve_tick_interval(None) == _TICK_INTERVAL_S


def test_a_positive_value_is_honoured():
    assert resolve_tick_interval("2") == 2


@pytest.mark.parametrize(
    "raw",
    ["", "abc", "2.5", "0", "-5"],
    ids=["empty", "words", "float", "zero", "negative"],
)
def test_an_unusable_value_degrades_to_the_default_instead_of_failing_boot(raw, caplog):
    """A typo in a unit file must not stop the daemon from starting — it falls back
    and says so, because a silent fallback would hide a tick interval nobody chose."""
    assert resolve_tick_interval(raw) == _TICK_INTERVAL_S
    assert "MY_CREW_TICK_INTERVAL_S" in caplog.text
