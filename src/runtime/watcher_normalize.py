"""Per-source normalization → stable hash for the wake-gate watcher (v31 P5).

The watcher's core metric is 0-LLM-when-nothing-changed, and its enemy is the
FALSE DIFF: a field that changes every poll (a computed age, a row index, a server
timestamp) would wake the agent — and burn an LLM run — on every tick. Each
`normalize_*` therefore projects its source payload to ONLY the fields whose change
a human would call "the source changed", sorts by a stable identity key, and hashes
the canonical JSON.

Field decisions (researcher-verified against the real read-tool models):
- Jira `Issue`: sort by `key`; labels sorted (Jira reorders them); the model carries
  no server `updated` timestamp, so nothing volatile to omit.
- GitHub `PullRequest`: sort by `number`; OMIT `age_days`/`stale` — both are computed
  per-poll from *today's date* and flip at midnight with zero source change (the
  critical false-diff); keep `updated_at` (a real source field).
- Sheets rows (hr-pack `Task` records): sort by a STABLE identity (email/id/title
  from `extra`), never the row index — inserting/deleting a row shifts every
  subsequent `source:i` id and would rehash the whole sheet as "changed".

Confluence and Linear are declared but FAIL-CLOSED (`NotSupportedError`) until a
real-page idempotency test exists — a silent best-effort normalize that drifts on
whitespace/version metadata would quietly burn LLM budget, which is worse than a
loud refusal at load.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class NotSupportedError(RuntimeError):
    """A watcher source that is declared but not (yet) supported — fail loud."""


#: Sources `run_watchers` accepts today. Kept in the loader's validation error message.
SUPPORTED_SOURCES = ("jira", "github", "sheets")


def normalize_and_hash(source: str, payload: Any) -> str:
    """Dispatch to the per-source normalizer; returns a stable sha256 hex digest."""
    if source == "jira":
        return _digest(normalize_jira(payload))
    if source == "github":
        return _digest(normalize_github(payload))
    if source == "sheets":
        return _digest(normalize_sheets(payload))
    if source in ("confluence", "linear"):
        raise NotSupportedError(
            f"watcher source {source!r} chưa hỗ trợ (fail-closed — cần idempotency "
            "test với nguồn thật trước khi mở)"
        )
    raise NotSupportedError(f"watcher source {source!r} không tồn tại")


def normalize_jira(issues: list[Any]) -> list[tuple]:
    """`Issue` list → stable tuples sorted by key; labels sorted."""
    rows = [
        (
            str(i.key), str(i.summary), str(i.status),
            str(i.assignee) if i.assignee else None,
            i.due_date.isoformat() if i.due_date else None,
            tuple(sorted(str(lb) for lb in i.labels)),
            bool(i.flagged),
        )
        for i in issues
    ]
    return sorted(rows, key=lambda r: r[0])


def normalize_github(prs: list[Any]) -> list[tuple]:
    """`PullRequest` list → stable tuples sorted by number; computed fields OMITTED."""
    rows = [
        (
            int(p.number), str(p.title),
            str(p.author) if p.author else None,
            p.updated_at.isoformat() if p.updated_at else None,
            str(p.review_decision) if p.review_decision else None,
            str(p.checks_state) if p.checks_state else None,
            # age_days / stale deliberately absent: computed per-poll from today's
            # date — including them would wake the agent every midnight.
        )
        for p in prs
    ]
    return sorted(rows, key=lambda r: r[0])


def normalize_sheets(tasks: list[Any]) -> list[tuple]:
    """hr-pack `Task` rows → stable tuples keyed by row identity, NOT row index."""
    rows = []
    for t in tasks:
        extra = dict(t.extra or ())
        # Stable identity: an email/id column when the sheet has one, else the title.
        # The `source:i` row-index id is NEVER used — a row insert shifts every index.
        key = str(extra.get("email") or extra.get("id") or t.title)
        rows.append(
            (
                key, str(t.status),
                str(t.assignee) if t.assignee else None,
                tuple(sorted(str(lb) for lb in t.labels)),
            )
        )
    return sorted(rows, key=lambda r: r[0])


def _digest(normalized: list[tuple]) -> str:
    canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
