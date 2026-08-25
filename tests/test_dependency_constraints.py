"""Dependency constraints that only break on a FRESH install.

A resolver picks versions at install time, so a missing upper bound is invisible to
every existing environment — the suite stays green while `pip install` on a clean
machine builds something that cannot import. These assert on the declared constraint
in `pyproject.toml`, not on what happens to be installed here, because the installed
version is exactly the evidence that cannot see the bug.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

# `packaging` arrives transitively and production code treats it as optional
# (mcp_session_pool falls back when it is absent), so this file must skip rather than
# error if it ever disappears — otherwise the guard's own dependency becomes the
# uncaught-at-install problem it exists to catch.
Requirement = pytest.importorskip("packaging.requirements").Requirement


def _dependencies() -> dict:
    raw = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    reqs = (Requirement(line) for line in raw["project"]["dependencies"])
    return {r.name.lower().replace("_", "-"): r for r in reqs}


def test_mcp_is_capped_below_2():
    """mcp 2.0.0 removed `mcp.shared.context.RequestContext`, which
    `langchain-mcp-adapters` still imports at module scope — and the adapter declares
    no upper bound of its own. Without this cap a clean resolve takes 2.x and every
    MCP-backed integration (Jira, Confluence, Slack) dies at import, while doctor
    reports it beside a "set the token" hint that cannot fix it.
    """
    mcp = _dependencies().get("mcp")
    assert mcp is not None, (
        "mcp must stay a DIRECT dependency: as a transitive one it is unpinnable here"
    )

    forbids_2 = not mcp.specifier.contains("2.0.0", prereleases=True)
    assert forbids_2, (
        f"mcp constraint {mcp.specifier!s} admits 2.0.0. Raise the cap only together "
        "with a langchain-mcp-adapters release that no longer imports RequestContext."
    )


def test_langchain_mcp_adapters_stays_pinned_exactly():
    """The cap above is only correct for adapter versions that import RequestContext.
    Pinning the adapter exactly means a bump has to be deliberate, and whoever makes it
    is forced past the test above rather than silently invalidating its reasoning.
    """
    adapter = _dependencies().get("langchain-mcp-adapters")
    assert adapter is not None, "langchain-mcp-adapters must stay a direct dependency"
    assert [s.operator for s in adapter.specifier] == ["=="], (
        f"expected an exact pin, got {adapter.specifier!s} — see test_mcp_is_capped_below_2"
    )


@pytest.mark.parametrize("name", ["mcp", "langchain-mcp-adapters"])
def test_constrained_packages_are_actually_importable(name):
    """The constraint is only meaningful if the resolved version imports. Guards the
    case where a cap is technically satisfied but the environment is still broken.
    """
    pytest.importorskip(name.replace("-", "_"))
