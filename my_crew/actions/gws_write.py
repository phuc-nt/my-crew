"""gws_write WRITE — Google Sheets/Docs mutations via the `gws` CLI (v31 P4).

Action shape: `{"type": "gws_write", "argv": [...], "dedup_hint": ...}` where argv is
the gws subcommand WITHOUT the binary (mirrors gh_cli). Only the fixed 3-prefix table
(`hard_block._GWS_ALLOWLIST_PREFIXES`) may run:

    sheets +append --spreadsheet ID --values 'a,b,c'
    docs documents create --json '{"title": "..."}'      (creates an EMPTY doc)
    docs +write --document ID --text '...'

"Create a doc with content" is deliberately two commands (create → +write) — gws
0.13.2's documents.create ignores provided content (pre-flight verified). Gmail is
NOT here: outbound mail is the `email_send` type.

Credentials: gws authenticates via its own OAuth keyring — nothing rides on the
action/audit. The handler RE-ENFORCES the full Lớp A verdict before spawning (F1:
never assume classify ran), spawns with an argv LIST (no shell) and a bounded
timeout, and returns a short parsed summary (never the full API response).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

from my_crew.actions.hard_block import _hard_deny_gws

Handler = Callable[[dict[str, Any]], str]

_GWS_TIMEOUT_S = 30
_SUMMARY_MAX = 300


def make_gws_handler(gws_bin: str = "gws") -> Handler:
    """Build the gateway handler. `gws_bin` override exists for tests only."""

    def _handler(action: dict[str, Any]) -> str:
        # Re-enforce the ENTIRE policy verdict at the execution path — this handler can
        # be reached via approve-reentry/execute_approved, not only past classify().
        verdict = _hard_deny_gws(action)
        if verdict is not None:
            raise PermissionError(f"gws_write refused: {verdict.reason}")

        argv = [str(a) for a in action.get("argv", [])]
        try:
            proc = subprocess.run(  # noqa: S603 — argv list, no shell; prefix-table enforced
                [gws_bin, *argv],
                capture_output=True, text=True, timeout=_GWS_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"gws {' '.join(argv[:2])} timed out after {_GWS_TIMEOUT_S}s"
            ) from None
        except FileNotFoundError:
            raise RuntimeError(
                f"gws CLI not found ({gws_bin!r}) — cài gws và đăng nhập OAuth trước"
            ) from None
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:_SUMMARY_MAX]
            raise RuntimeError(f"gws exited {proc.returncode}: {detail}")
        return _summarize(argv, proc.stdout)

    return _handler


def _summarize(argv: list[str], stdout: str) -> str:
    """Short human summary from gws JSON output — ids/counts only, never the payload."""
    head = " ".join(argv[:3])
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return f"gws {head}: ok"
    if isinstance(data, dict):
        doc_id = data.get("documentId")
        updates = data.get("updates")
        if isinstance(updates, dict):
            cells = updates.get("updatedCells")
            rng = updates.get("updatedRange")
            return f"gws {head}: appended {cells or '?'} cells ({rng or '?'})"
        # docs.batchUpdate (+write) ALSO returns documentId — distinguish by argv, not
        # by response shape, so a +write never reads as a create.
        if doc_id and argv[:2] == ["docs", "+write"]:
            return f"gws {head}: document {doc_id} updated"
        if doc_id:
            title = str(data.get("title") or "")
            return f"gws {head}: created document {doc_id}" + (f" ('{title}')" if title else "")
    return f"gws {head}: ok"
