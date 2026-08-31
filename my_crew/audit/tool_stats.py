"""Per-tool call statistics, aggregated from the audit trail.

Answers "which tool is failing, and which is slow" with numbers instead of a hand-read
log. Read-only and derived: the rows are written once, by the policy shim in
`read_only_toolset`, and this module only counts them. There is deliberately no second
writer and no counter table — a tally kept alongside the trail is a tally that can drift
from it, and then neither number can be trusted.

What each field means, given how the shim records:

- `denied` is a POLICY refusal (classify blocked the call); it never ran.
- `failures` is a call that ran and whose body raised — a timeout, a 500, a bad response.
  These are different problems with different fixes, so they are never summed together.
- `avg_duration_ms` covers calls that actually ran (allowed ones), since a denial's
  elapsed time measures the classifier, not the tool.
- `common_errors` ranks the denial reasons; a body failure's message is not on the trail
  (the shim records the outcome, not the exception text) so it cannot be ranked here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The `action_type` the read-tool shim stamps on its rows. Other action types on the same
#: shared trail (gateway writes, `web.search`) are not tool-call telemetry and are skipped.
READ_CALL_ACTION = "mcp_tool_read"


@dataclass
class ToolStats:
    """One tool's tally. `total_calls` counts every recorded attempt, denials included."""

    tool: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    denied: int = 0
    avg_duration_ms: float = 0.0
    common_errors: list[tuple[str, int]] = field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        """Share of attempts that did not return data (body failures AND denials).

        Both are a call the model asked for and did not get an answer from, which is the
        thing an operator is scanning for; the breakdown stays available in the fields.
        """
        if not self.total_calls:
            return 0.0
        return (self.failures + self.denied) / self.total_calls


def _rows(path: Path, since: str | None, actor: str | None) -> list[dict[str, Any]]:
    from my_crew.audit.audit_log import AuditLog

    rows = AuditLog(path).query(since=since, actor=actor)
    return [r for r in rows if r.get("action_type") == READ_CALL_ACTION]


def collect_tool_stats(
    path: Path, *, since: str | None = None, actor: str | None = None
) -> list[ToolStats]:
    """Per-tool stats from the trail at `path`, worst failure rate first.

    Ordered by what an operator is looking for rather than alphabetically: the tool most
    often failing, then the busiest among equals. A missing or empty trail is not an error
    — it means nothing has been recorded yet.
    """
    durations: dict[str, list[int]] = {}
    reasons: dict[str, Counter[str]] = {}
    stats: dict[str, ToolStats] = {}

    for row in _rows(path, since, actor):
        tool = str(row.get("tool") or "")
        if not tool:
            continue
        stat = stats.setdefault(tool, ToolStats(tool=tool))
        stat.total_calls += 1

        if row.get("verdict") == "deny":
            stat.denied += 1
            reason = str(row.get("reason") or "").strip()
            if reason:
                reasons.setdefault(tool, Counter())[reason] += 1
            continue

        # `result_summary` carries the body outcome. Rows written before it existed have
        # none; counting those as failures would invent a spike out of missing data, so an
        # absent value reads as the success it was recorded as.
        if str(row.get("result_summary") or "ok") == "error":
            stat.failures += 1
        else:
            stat.successes += 1
        elapsed = row.get("params", {}).get("elapsed_ms")
        if isinstance(elapsed, int | float):
            durations.setdefault(tool, []).append(int(elapsed))

    for tool, stat in stats.items():
        samples = durations.get(tool, [])
        stat.avg_duration_ms = round(sum(samples) / len(samples), 1) if samples else 0.0
        stat.common_errors = reasons.get(tool, Counter()).most_common(3)

    return sorted(stats.values(), key=lambda s: (-s.failure_rate, -s.total_calls, s.tool))


def render_tool_stats(stats: list[ToolStats]) -> str:
    """A fixed-width table for an operator. Empty input says so rather than printing
    a bare header, which reads as "all tools are healthy"."""
    if not stats:
        return "Chưa có lượt gọi công cụ nào được ghi nhận."

    head = f"{'công cụ':<24} {'gọi':>6} {'ok':>6} {'lỗi':>6} {'chặn':>6} {'ms/lượt':>9}"
    lines = [head, "-" * len(head)]
    for s in stats:
        lines.append(
            f"{s.tool[:24]:<24} {s.total_calls:>6} {s.successes:>6} "
            f"{s.failures:>6} {s.denied:>6} {s.avg_duration_ms:>9.1f}"
        )
        for reason, count in s.common_errors:
            lines.append(f"    ↳ {count}× {reason[:60]}")
    return "\n".join(lines)
