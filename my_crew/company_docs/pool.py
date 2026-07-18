"""Resolve a profile's `company_docs:` slug list into CompanyDoc objects (v7 M19).

The seam the graph-build entry points (worker / cron / cli) call to wire opted-in company
docs into the `ProfileContext`. Mirrors `skills/skill_pool.load_skill_pool`: empty list ⇒ ()
with NO disk read, so the no-docs path stays byte-identical. A slug that no longer resolves to
a file is warned and dropped (a stale opt-in must not crash a run — graceful, like skills)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from my_crew.company_docs.store import get_doc

if TYPE_CHECKING:
    from my_crew.company_docs.store import CompanyDoc

logger = logging.getLogger(__name__)


def load_company_docs(slugs: tuple[str, ...]) -> tuple[CompanyDoc, ...]:
    """Load the named docs, preserving the profile's declared order.

    Empty `slugs` ⇒ () with no disk read. A slug with no matching file is warned and dropped
    (a typo/deleted-doc in profile.yaml must not crash a run)."""
    if not slugs:
        return ()
    out: list[CompanyDoc] = []
    for slug in slugs:
        try:
            doc = get_doc(slug)
        except ValueError:  # invalid slug in profile.yaml — skip, don't crash
            logger.warning("profile company_doc slug %r invalid; skipped", slug)
            continue
        if doc is None:
            logger.warning("profile company_doc %r not found in library; skipped", slug)
            continue
        out.append(doc)
    return tuple(out)
