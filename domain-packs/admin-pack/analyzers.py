"""admin-pack analyzers (v3 M8): pure fleet aggregations + deterministic renders.

Every number in an admin report comes from these pure functions over the state
snapshots — the LLM only narrates (same discipline as PM/HR). Each report kind has a
build_* (aggregate) and a render_*_slack (deterministic text); the shared fallback
keeps the numbers deliverable when the narrative LLM call fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FleetReport:
    """One admin kind's deterministic content, ready to render/narrate."""

    kind: str
    headline: str            # one-line deterministic summary (totals)
    rows: list[dict] = field(default_factory=list)   # per-agent table rows
    alerts: list[dict] = field(default_factory=list)  # relevant team_alerts entries


def build_cost_rollup(payload: dict) -> FleetReport:
    """Total + per-agent spend vs cap; alert rows for agents near/over cap."""
    agents = payload.get("agents", [])
    total = sum(a.get("budget_spent_usd", 0.0) for a in agents)
    cap_total = sum(a.get("budget_cap_usd", 0.0) for a in agents)
    rows = [
        {
            "agent_id": a["agent_id"],
            "spent_usd": round(a.get("budget_spent_usd", 0.0), 4),
            "cap_usd": a.get("budget_cap_usd", 0.0),
            "ratio": round(a.get("budget_ratio", 0.0), 3),
        }
        for a in sorted(agents, key=lambda x: -x.get("budget_spent_usd", 0.0))
    ]
    alerts = [al for al in payload.get("alerts", []) if al["kind"] == "budget"]
    headline = (
        f"Tổng chi phí LLM tháng này: ${total:.4f} / trần đội ${cap_total:.2f} "
        f"({len(agents)} agent, {len(alerts)} cảnh báo budget)"
    )
    return FleetReport(kind="cost-rollup", headline=headline, rows=rows, alerts=alerts)


def build_guardrail_health(payload: dict) -> FleetReport:
    """Gateway verdict mix + pending queue per agent — is the guardrail healthy?"""
    agents = payload.get("agents", [])
    rows = []
    total_deny = total_pending = 0
    for a in agents:
        counts = a.get("audit_counts", {})
        pending = len(a.get("pending_approvals", []))
        total_deny += counts.get("deny", 0)
        total_pending += pending
        rows.append(
            {
                "agent_id": a["agent_id"],
                "allow": counts.get("allow", 0),
                "dry_run": counts.get("dry_run", 0),
                "deny": counts.get("deny", 0),
                "pending_approvals": pending,
            }
        )
    alerts = [
        al for al in payload.get("alerts", [])
        if al["kind"] in ("approval_stuck", "deny_spike")
    ]
    headline = (
        f"Guardrail 7 ngày: {total_deny} deny toàn đội, {total_pending} approval đang chờ, "
        f"{len(alerts)} cảnh báo"
    )
    return FleetReport(kind="guardrail-health", headline=headline, rows=rows, alerts=alerts)


def build_audit_digest(payload: dict) -> FleetReport:
    """Fleet activity digest: last run + verdict totals per agent (anomaly hunting)."""
    agents = payload.get("agents", [])
    rows = []
    for a in agents:
        last = a.get("last_run") or {}
        counts = a.get("audit_counts", {})
        rows.append(
            {
                "agent_id": a["agent_id"],
                "enabled": a.get("enabled", False),
                "last_run": f"{last.get('kind', '—')} {last.get('status', '')}".strip(),
                "audit_events_7d": sum(counts.values()),
                "deny": counts.get("deny", 0),
            }
        )
    disabled = sum(1 for a in agents if not a.get("enabled"))
    never_ran = sum(1 for a in agents if not a.get("last_run"))
    headline = (
        f"Đội {len(agents)} agent: {disabled} đang tắt, {never_ran} chưa từng chạy, "
        f"{len(payload.get('alerts', []))} cảnh báo tổng"
    )
    return FleetReport(
        kind="audit-digest", headline=headline, rows=rows,
        alerts=list(payload.get("alerts", [])),
    )


BUILDERS = {
    "cost-rollup": build_cost_rollup,
    "guardrail-health": build_guardrail_health,
    "audit-digest": build_audit_digest,
}

_TITLES = {
    "cost-rollup": "Chi phí LLM toàn đội",
    "guardrail-health": "Sức khỏe guardrail",
    "audit-digest": "Nhật ký hoạt động đội agent",
}


def render_fleet_slack(report: FleetReport, *, report_date: str) -> str:
    """Deterministic Slack text: headline + bounded per-agent lines + alerts."""
    lines = [f"*🛠 {_TITLES.get(report.kind, report.kind)} — {report_date}*", report.headline]
    for row in report.rows[:10]:
        cells = ", ".join(f"{k}={v}" for k, v in row.items() if k != "agent_id")
        lines.append(f"• `{row['agent_id']}`: {cells}")
    if len(report.rows) > 10:
        lines.append(f"… (+{len(report.rows) - 10} agent)")
    for al in report.alerts[:8]:
        icon = "🔴" if al.get("severity") == "high" else "🟡"
        lines.append(f"{icon} `{al['agent_id']}`: {al['message']}")
    return "\n".join(lines)


def fallback_fleet_narrative(report: FleetReport) -> str:
    """Numbers-only narrative when the LLM call fails — the digest still ships."""
    return f"{report.headline}. (Không có nhận xét tự động cho lần chạy này.)"
