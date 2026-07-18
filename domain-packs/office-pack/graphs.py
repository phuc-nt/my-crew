"""office-pack graph contributions (v12 M28b).

Every pack ships a `graphs.py` (the marker file `PackRegistry` discovery keys off) that
exports `REPORT_KINDS`. The coordinator's actual work does not run as a `--report`
kind at all — it runs as the `team-tick` pseudo-kind (mirroring `inbox`/`tasks`/
`ops-alerts`/`team-step`), dispatched from `worker.py` straight into
`my_crew.runtime.team_tick_runner`, never through this pack's report dispatch table. So
`REPORT_KINDS` is intentionally empty: office-pack still needs to exist as a real,
loadable domain (so `create_agent` accepts `domain: office` and
`PackRegistry().load("office")` resolves `pack.allowlist` for the coordinator's
red-line default-deny test), but it contributes no report graph builder.

Kept as a real module (not folded into `__init__.py`) to match the file-per-seam
convention every other pack (`hr-pack`, `admin-pack`) already uses.
"""

from __future__ import annotations

#: No report-kind graph builders — coordinator work runs as the `team-tick`
#: pseudo-kind, not a `--report` dispatch. See module docstring.
REPORT_KINDS: dict = {}
