"""Append-only audit log (PDR §7.1).

Every Action Gateway decision writes one immutable JSON line to a JSONL file
under the data dir. No audit => no write is allowed. Entries are append-only:
the file is opened in append mode and never rewritten.

Redaction uses the shared secret detector (my_crew.actions.secret_patterns): it masks
secret-bearing keys AND secret patterns inside free-text values, so a credential
the gateway can detect can never be written verbatim into the immutable audit
trail (PDR §7.9 Lớp A). Every string field of an entry is redacted, not just keyed
dict values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_crew.actions.secret_patterns import redact

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class AuditEntry:
    """One audit record. `params` is redacted on write."""

    action_type: str  # e.g. "mcp_tool", "gh_cli", "llm"
    tool: str  # e.g. "confluence:updatePage", "gh:pr-create"
    verdict: str  # "allow" | "deny" | "dry_run" | "skipped"
    reason: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    dry_run: bool = False
    rationale: str = ""  # why the agent chose this action
    # v46: the agent that performed the action (its profile_id). "" for pre-v46 rows / callers that
    # do not set it. Recorded so a cross-agent governance dashboard can filter by the ACTOR field
    # instead of reconstructing identity from the per-agent data_dir path the JSONL lives under.
    actor: str = ""
    timestamp: str = field(default_factory=_utc_now_iso)


class AuditLog:
    """Append-only JSONL writer."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def record(self, entry: AuditEntry) -> None:
        """Append one entry as a single JSON line, redacting every field.

        The whole payload is redacted (params, reason, result_summary, rationale,
        ...) so a secret cannot leak through any free-text field — including on a
        credential-deny, where the offending value would otherwise be echoed.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = redact(asdict(entry))
        line = json.dumps(payload, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def query(
        self,
        *,
        tool: str | None = None,
        verdict: str | None = None,
        since: str | None = None,
        actor: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read audit entries, newest first, with optional filters.

        Filters: `tool` (substring, case-insensitive), `verdict` (exact),
        `since` (ISO date/datetime prefix — entries with timestamp >= it),
        `actor` (v46, exact agent id — only rows recorded with that actor; pre-v46 rows have no
        actor and are excluded by this filter). `limit` caps the result count. Returns
        already-redacted records (they were redacted at write time).
        """
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip a corrupt line rather than fail the whole query
                if tool and tool.lower() not in str(entry.get("tool", "")).lower():
                    continue
                if verdict and entry.get("verdict") != verdict:
                    continue
                if since and str(entry.get("timestamp", "")) < since:
                    continue
                if actor is not None and entry.get("actor", "") != actor:
                    continue
                out.append(entry)
        out.reverse()  # newest first
        return out[:limit] if limit else out
