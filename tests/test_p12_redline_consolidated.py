"""M3-P12 S4: consolidated red-line — the WHOLE P12 surface keeps the gateway invariant.

A single integration-level gate re-asserting: D3 proposes (never auto-executes), the
automation package imports the gateway only, B4 tracing adds no action path, and B3 replay
re-runs gateway-routed graphs (no replay-specific write bypass).
"""

from __future__ import annotations

import pathlib

from my_crew.runtime import replay, run_config

_AUTOMATION_DIR = pathlib.Path("my_crew/automation")
_FORBIDDEN = ("slack_write", "linear_write", "email_write", "confluence_write",
             "approved_dispatch", "mcp_adapter")


def _import_lines(src: str) -> str:
    return "\n".join(
        ln for ln in src.splitlines() if ln.strip().startswith(("import ", "from "))
    )


def test_automation_pkg_imports_gateway_only():
    """Re-assert at integration level: no automation file imports a write executor."""
    for pyfile in _AUTOMATION_DIR.glob("*.py"):
        imports = _import_lines(pyfile.read_text(encoding="utf-8"))
        for bad in _FORBIDDEN:
            assert bad not in imports, f"{pyfile.name} imports {bad}"
        assert "call_tool(" not in pyfile.read_text(encoding="utf-8")


def test_b4_tracing_module_has_no_action_path():
    """B4 is observability-only: run_config imports no gateway/write/action module."""
    src = pathlib.Path(run_config.__file__).read_text(encoding="utf-8")
    imports = _import_lines(src)
    forbidden = (
        "action_gateway", "slack_write", "linear_write", "email_write", "approved_dispatch",
    )
    for bad in forbidden:
        assert bad not in imports


def test_b3_replay_module_has_no_write_path():
    """B3 replay re-runs an existing graph; it imports no write executor / gateway bypass."""
    src = pathlib.Path(replay.__file__).read_text(encoding="utf-8")
    imports = _import_lines(src)
    for bad in ("slack_write", "linear_write", "email_write", "approved_dispatch", "call_tool"):
        assert bad not in imports
    # replay only re-invokes the compiled graph — no direct execute/approve.
    assert ".execute_approved(" not in src
    assert ".approve(" not in src
