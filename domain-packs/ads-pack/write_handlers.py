"""ads-pack write handlers + allowlist (P6) — MVP is read-only, ZERO writes.

`ALLOWLIST` stays empty: campaign create/edit is explicitly out of scope for this MVP
(phase spec: "tạo/sửa campaign = ngoài scope, ghi roadmap"). This file exists (rather
than being omitted) so the pack skeleton stays uniform with every other domain-pack and
so a future write-enabled version has an obvious place to land its allowlist entries.
"""

from __future__ import annotations

#: server → permitted write tool names. Empty ⇒ ads-pack writes nothing (MVP is read-only).
ALLOWLIST: dict[str, tuple[str, ...]] = {}
