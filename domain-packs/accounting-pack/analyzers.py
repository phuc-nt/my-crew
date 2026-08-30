"""accounting-pack cashflow-weekly analyzer + presentation (P6).

Pure functions over `LedgerRow` records (see `tools.py`). Numbers are computed here
deterministically — same "numbers never come from the LLM" invariant as ads-pack/
hr-pack; the LLM only writes qualitative narrative around the table this module builds.

Fail-degrade: when the ToolProvider could not read the ledger (`rows is None`), this
module renders the exact sentinel token "THIẾU" in place of every metric rather than
raising or fabricating a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The exact sentinel token used repo-wide for "could not retrieve this data point".
THIEU = "THIẾU"


@dataclass(frozen=True)
class CashflowWeeklyReport:
    """cashflow-weekly snapshot: thu/chi/công nợ ròng, or degraded (no data)."""

    available: bool  # False ⇒ the ledger read failed; every number below is THIEU in render
    total_income: float = 0.0
    total_expense: float = 0.0
    net: float = 0.0
    unclassified_count: int = 0  # rows whose type column didn't match thu/chi tokens
    entry_count: int = 0
    entries: tuple = field(default_factory=tuple)


def build_cashflow_weekly(rows: list | None) -> CashflowWeeklyReport:
    """Aggregate `LedgerRow`s into income/expense/net totals. `rows is None` ⇒ degraded
    report (ledger read failed). `rows == []` is genuinely-empty-but-successful (no
    entries this period) — NOT degraded, totals are legitimately 0."""
    if rows is None:
        return CashflowWeeklyReport(available=False)

    total_income = 0.0
    total_expense = 0.0
    unclassified = 0
    for r in rows:
        if r.kind == "income":
            total_income += r.amount
        elif r.kind == "expense":
            total_expense += r.amount
        else:
            unclassified += 1

    return CashflowWeeklyReport(
        available=True,
        total_income=round(total_income, 2),
        total_expense=round(total_expense, 2),
        net=round(total_income - total_expense, 2),
        unclassified_count=unclassified,
        entry_count=len(rows),
        entries=tuple(rows),
    )


def render_cashflow_weekly_text(report: CashflowWeeklyReport, report_date: str) -> str:
    """Deterministic plain-text summary for the Telegram body (no LLM, no HTML)."""
    lines = [f"Báo cáo dòng tiền — tuần đến {report_date}"]
    if not report.available:
        lines.append(f"Tổng thu: {THIEU} (không đọc được sổ quỹ)")
        lines.append(f"Tổng chi: {THIEU}")
        lines.append(f"Chênh lệch: {THIEU}")
        return "\n".join(lines)

    lines.append(f"Tổng thu: {report.total_income:,.2f}")
    lines.append(f"Tổng chi: {report.total_expense:,.2f}")
    lines.append(f"Chênh lệch (thu - chi): {report.net:,.2f}")
    lines.append(f"Số dòng ghi nhận: {report.entry_count}")
    if report.unclassified_count:
        lines.append(
            f"Lưu ý: {report.unclassified_count} dòng không xác định được loại "
            "thu/chi (kiểm tra cột loại trong sổ)."
        )
    return "\n".join(lines)


def fallback_cashflow_weekly_narrative(report: CashflowWeeklyReport) -> str:
    """Deterministic prose used when the LLM narrate call fails — never blocks delivery."""
    if not report.available:
        return f"Không đọc được sổ quỹ kỳ này ({THIEU})."
    return (
        f"Tuần này thu {report.total_income:,.2f}, chi {report.total_expense:,.2f}, "
        f"chênh lệch {report.net:,.2f}."
    )
