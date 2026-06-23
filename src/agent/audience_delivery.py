"""Audience-aware delivery routing — channel + dedup hint per audience.

Phase 5: the 3 report graphs all need the same rule to pick the Slack channel and
dedup namespace for `internal` vs `external` delivery. Factored here so the rule
(and the fail-fast guard) lives in one place.

- internal → channel None (the default `slack_report_channel`), dedup hint
  `{kind}-{today}` UNCHANGED (backward-compat).
- external → channel = `slack_stakeholder_channel` (must be set, else raise — never
  silently fall back to the internal channel), dedup hint `{kind}-external-{today}`.

The external channel is (by the Slice-A config validation) in
`slack_external_channels`, so `hard_block.needs_interrupt` routes the post to Lớp B
approval — no gateway/allowlist change needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.reporting_config import ReportingConfig

# Slack statuses that count as a successful (or accepted) delivery. `pending_approval`
# is success for external: the post is correctly queued for human approval, not failed.
SLACK_OK_STATUSES = frozenset({"executed", "dry_run", "deduplicated", "pending_approval"})


def resolve_audience_delivery(
    audience: str, kind: str, today: str, config: ReportingConfig
) -> tuple[str | None, str]:
    """Return (slack_channel, dedup_date_hint) for the given audience.

    Raises RuntimeError if `audience="external"` but no stakeholder channel is
    configured — external must never fall back to the internal channel.
    """
    if audience == "external":
        channel = config.slack_stakeholder_channel
        if not channel:
            raise RuntimeError(
                "SLACK_STAKEHOLDER_CHANNEL is not set; required for --audience external "
                "(and it must be listed in SLACK_EXTERNAL_CHANNELS for Lớp B approval)."
            )
        return channel, f"{kind}-external-{today}"
    return None, f"{kind}-{today}"  # internal: unchanged dedup hint, default channel


def delivery_summary(conf_status: str, slack_result, detail_url: str | None) -> str:
    """Build the deliver-summary string, surfacing an approval id when pending."""
    summary = f"confluence={conf_status} slack={slack_result.status}"
    if getattr(slack_result, "approval_id", None) is not None:
        summary += f" approval_id={slack_result.approval_id}"
    return summary + f" url={detail_url}"
