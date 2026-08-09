"""Audit hash-chain (v76, learned from my-dandori's 4-layer audit defense).

The JSONL trail was append-only by CODE DISCIPLINE only — anything with write access
to the data dir (a compromised process, a careless human) could rewrite history and
the trail itself would never notice. This module makes tampering DETECTABLE: every
entry carries `prev_hash` + `entry_hash`, and `verify_chain` walks the file and
reports the first break with a reason.

Canonical encoding is length-prefixed (8-byte big-endian length before every key and
value), NOT a delimiter join — `"a|b" + "c"` and `"a" + "b|c"` collide under a join
but cannot under length-prefixing (`test_audit_chain.py` constructs the collision).

Threat-model honesty (same note my-dandori writes): on a single machine the chain
detects EDITS and MID-FILE deletions; deleting the newest rows (truncation) leaves a
self-consistent chain and needs an out-of-band checkpoint to catch — deliberately
deferred until there is a second machine to hold one.

Concurrency: several worker processes append to the SHARED team-tasks trail, so the
read-tail + append pair runs under an exclusive `flock` on a sidecar lock file. Audit
must never block work: any chain-bookkeeping failure degrades to appending the entry
with `prev_hash=""` (a visible chain RESTART, which `verify_chain` reports as info,
never a silent drop of the audit row itself).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

#: Payload keys excluded from the hash: the hash fields themselves.
_HASH_FIELDS = ("entry_hash", "prev_hash")


def canonical_hash(payload: dict[str, Any]) -> str:
    """sha256 over a length-prefixed encoding of the payload (sorted keys).

    Every key and value (value as compact JSON) is prefixed with its byte length as
    8-byte big-endian — no delimiter exists for content to collide against.
    `prev_hash` IS included (that is what links the chain); `entry_hash` is not.
    """
    h = hashlib.sha256()
    for key in sorted(payload):
        if key == "entry_hash":
            continue
        value = json.dumps(payload[key], ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
        for part in (key.encode("utf-8"), value.encode("utf-8")):
            h.update(len(part).to_bytes(8, "big"))
            h.update(part)
    return h.hexdigest()


def chain_fields(payload: dict[str, Any], prev_hash: str) -> dict[str, Any]:
    """Return `payload` + the two chain fields, ready to serialize."""
    linked = {**payload, "prev_hash": prev_hash}
    return {**linked, "entry_hash": canonical_hash(linked)}


def read_tip_hash(path: Path) -> str:
    """The last line's `entry_hash` ("" for a missing/empty file or a legacy tail).

    Reads only the file tail (last 64KiB) — the trail grows unbounded and the writer
    calls this on every record.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size == 0:
        return ""
    with path.open("rb") as fh:
        fh.seek(max(0, size - 65536))
        tail = fh.read().decode("utf-8", errors="replace")
    for line in reversed(tail.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return str(json.loads(line).get("entry_hash") or "")
        except json.JSONDecodeError:
            return ""
    return ""


def verify_chain(path: Path) -> dict[str, Any]:
    """Walk the whole trail; return a verdict dict (never raises on content).

    {ok, total, hashed, legacy_prefix, restarts, broken_line, reason}
      - reason "tamper": a line's entry_hash does not match its own content;
      - reason "chain": entry_hash valid but prev_hash does not link to the
        previous hashed line (an edit/delete/insert between them);
      - restarts: count of prev_hash=="" rows after the first hashed row — each is a
        visible chain restart (bookkeeping degrade), reported, not hidden.
    Legacy rows (no entry_hash — pre-v76) are only valid as an unbroken PREFIX;
    a legacy row appearing after hashed rows is itself a "chain" break (an attacker
    must not be able to erase history by stripping hash fields).
    """
    result: dict[str, Any] = {"ok": True, "total": 0, "hashed": 0, "legacy_prefix": 0,
                              "restarts": 0, "broken_line": None, "reason": ""}
    if not path.exists():
        return result
    prev = ""
    seen_hashed = False
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            result["total"] += 1
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                result.update(ok=False, broken_line=lineno, reason="tamper")
                return result
            entry_hash = str(payload.get("entry_hash") or "")
            if not entry_hash:
                if seen_hashed:
                    result.update(ok=False, broken_line=lineno, reason="chain")
                    return result
                result["legacy_prefix"] += 1
                continue
            if canonical_hash(payload) != entry_hash:
                result.update(ok=False, broken_line=lineno, reason="tamper")
                return result
            prev_hash = str(payload.get("prev_hash") or "")
            if seen_hashed and prev_hash != prev:
                if prev_hash == "":
                    result["restarts"] += 1  # visible degrade restart, not a break
                else:
                    result.update(ok=False, broken_line=lineno, reason="chain")
                    return result
            result["hashed"] += 1
            seen_hashed = True
            prev = entry_hash
    return result
