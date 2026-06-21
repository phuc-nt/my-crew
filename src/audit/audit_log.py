"""Append-only audit log (PDR §7.1).

Every Action Gateway decision writes one immutable JSON line to a JSONL file
under the data dir. No audit => no write is allowed. Entries are append-only:
the file is opened in append mode and never rewritten.

Redaction uses the shared secret detector (src.actions.secret_patterns): it masks
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

from src.actions.secret_patterns import redact
from src.config.settings import get_settings

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
    timestamp: str = field(default_factory=_utc_now_iso)


class AuditLog:
    """Append-only JSONL writer."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_settings().data_dir / "audit" / "audit.jsonl")

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
