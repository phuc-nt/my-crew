"""Fixture factory for full-flow scenarios.

`fullflow` yields a builder so each test picks its own LLM script and company
flags BEFORE the harness installs its patches. The trace JSONL is always
written on teardown — pass or fail — so a red scenario ships its own evidence.
"""

from __future__ import annotations

import pytest

from .harness import FullFlowHarness


@pytest.fixture
def fullflow(tmp_path, monkeypatch):
    built: list[FullFlowHarness] = []

    def _build(**kwargs) -> FullFlowHarness:
        harness = FullFlowHarness(tmp_path, monkeypatch, **kwargs)
        built.append(harness)
        return harness

    yield _build

    for harness in built:
        path = harness.write_trace()
        # The path is printed so a failing run's report points straight at the
        # per-hop evidence (pytest only shows it for failures, with -s always).
        print(f"\n[fullflow trace] {path}")
