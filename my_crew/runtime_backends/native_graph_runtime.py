"""NativeGraphRuntime (v20 Phase 1) — the existing graphs, behind the seam.

Delegates straight to the unchanged builders (`build_graph_for` for reports,
`build_team_task_graph` for team steps). No prompt/state layer is added, so a native agent's
output is byte-identical to pre-v20. This is the default backend and the fallback for the
kill-switch / None-degrade paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from my_crew.profile.loader import LoadedProfile


class NativeGraphRuntime:
    """Wrap the native one-shot graph builders (no behavior change)."""

    def build_report(self, loaded: LoadedProfile, settings: Any, kind: str, audience: str):
        # Imported here (not at module top) to avoid a heavy import chain at package load.
        from my_crew.runtime.worker import build_graph_for

        return build_graph_for(loaded, settings, kind, audience)

    def build_task(self, **kwargs: Any):
        from my_crew.agent.team_task_graph import build_team_task_graph

        return build_team_task_graph(**kwargs)
