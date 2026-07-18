"""Domain packs (v3 M5): the outer harness that makes the core multi-domain.

A *pack* bundles everything domain-specific (PM / HR / Admin) that the otherwise
generic core needs to run an agent of that domain: which report kinds it serves,
how it reads its source systems (ToolProvider), which write tools it may use
(allowlist contribution), its prompts, and its skill pool. The core (worker,
profile loader, Action Gateway, memory, web UI) stays domain-agnostic and asks the
active pack for these pieces instead of hardcoding PM.

This package is scaffolding in S1 — `Pack` and `PackRegistry` carry empty defaults
so nothing dispatches through them yet. Later M5 slices populate them seam by seam
(S2 report-kind dispatch, S3 ToolProvider, S4 allowlist, S5 prompts/skills) while
the existing hardcoded paths keep working until each seam is moved.
"""

from __future__ import annotations

from my_crew.packs.registry import DEFAULT_DOMAIN, Pack, PackRegistry
from my_crew.packs.tool_provider import ToolProvider

__all__ = ["DEFAULT_DOMAIN", "Pack", "PackRegistry", "ToolProvider"]
