"""ads-pack ads-weekly analyzer + presentation (P6).

Pure functions over `InsightRow` records (see `tools.py`). Numbers are computed here
deterministically — the LLM (in `graphs.py`) only writes qualitative narrative around
the table `render_ads_weekly_text` produces, mirroring hr-pack's
"numbers never come from the LLM" invariant.

Fail-degrade: when the ToolProvider could not reach the Meta API (`rows is None`), this
module renders the exact sentinel token "THIẾU" in place of every metric rather than
raising or fabricating a number (phase non-functional requirement: "pack lỗi API ngoài
→ fail-degrade ghi THIẾU đúng chuẩn sentinel, không bịa số").
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The exact sentinel token used repo-wide for "could not retrieve this data point"
#: (see collect_prefetch.py / team_step_runner.py / web_search_tool.py convention).
THIEU = "THIẾU"


@dataclass(frozen=True)
class CampaignTotals:
    """One campaign's aggregate spend/reach/CTR over the reporting window."""

    campaign_id: str
    campaign_name: str
    spend: float
    reach: int
    ctr_avg: float  # simple mean of the per-day ctr values, not reach-weighted (MVP)


@dataclass(frozen=True)
class AdsWeeklyReport:
    """ads-weekly snapshot: per-campaign totals + grand total, or degraded (no data)."""

    available: bool  # False ⇒ the API read failed; every number below is THIEU in render
    campaigns: tuple[CampaignTotals, ...] = field(default_factory=tuple)
    total_spend: float = 0.0
    total_reach: int = 0


def build_ads_weekly(rows: list | None) -> AdsWeeklyReport:
    """Group `InsightRow`s by campaign. `rows is None` ⇒ degraded report (API failed).
    `rows == []` is a genuinely-empty-but-successful read (no campaigns ran) — NOT
    degraded, since the source answered fine; total_spend/reach are legitimately 0.
    """
    if rows is None:
        return AdsWeeklyReport(available=False)

    by_campaign: dict[str, list] = {}
    for r in rows:
        by_campaign.setdefault(r.campaign_id, []).append(r)

    campaigns = []
    total_spend = 0.0
    total_reach = 0
    for campaign_id, campaign_rows in sorted(by_campaign.items()):
        spend = sum(r.spend for r in campaign_rows)
        reach = sum(r.reach for r in campaign_rows)
        ctr_avg = sum(r.ctr for r in campaign_rows) / len(campaign_rows) if campaign_rows else 0.0
        campaigns.append(
            CampaignTotals(
                campaign_id=campaign_id,
                campaign_name=campaign_rows[0].campaign_name,
                spend=round(spend, 2),
                reach=reach,
                ctr_avg=round(ctr_avg, 4),
            )
        )
        total_spend += spend
        total_reach += reach

    campaigns.sort(key=lambda c: -c.spend)
    return AdsWeeklyReport(
        available=True,
        campaigns=tuple(campaigns),
        total_spend=round(total_spend, 2),
        total_reach=total_reach,
    )


def render_ads_weekly_text(report: AdsWeeklyReport, report_date: str) -> str:
    """Deterministic plain-text table for the Telegram body (no LLM, no HTML — the
    push graph sends this as a Telegram message, same shape as personal-pack)."""
    lines = [f"Báo cáo quảng cáo Meta Ads — tuần đến {report_date}"]
    if not report.available:
        lines.append(f"Tổng chi tiêu: {THIEU} (không đọc được dữ liệu từ Meta API)")
        lines.append(f"Tổng lượt tiếp cận (reach): {THIEU}")
        return "\n".join(lines)

    lines.append(f"Tổng chi tiêu: {report.total_spend:,.2f}")
    lines.append(f"Tổng lượt tiếp cận (reach): {report.total_reach:,}")
    if not report.campaigns:
        lines.append("Không có chiến dịch nào chạy trong kỳ.")
        return "\n".join(lines)
    lines.append("")
    for c in report.campaigns:
        lines.append(
            f"• {c.campaign_name}: chi {c.spend:,.2f} · reach {c.reach:,} · "
            f"CTR TB {c.ctr_avg:.2%}"
        )
    return "\n".join(lines)


def fallback_ads_weekly_narrative(report: AdsWeeklyReport) -> str:
    """Deterministic prose used when the LLM narrate call fails — never blocks delivery."""
    if not report.available:
        return f"Không đọc được dữ liệu quảng cáo kỳ này ({THIEU})."
    return (
        f"Tuần này chi {report.total_spend:,.2f} trên {len(report.campaigns)} chiến dịch, "
        f"tiếp cận {report.total_reach:,} lượt."
    )
