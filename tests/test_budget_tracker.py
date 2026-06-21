"""Budget tracker: accumulation, warn threshold, hard-stop, unknown cost, corruption."""

from __future__ import annotations

import json

import pytest

from src.llm.budget_tracker import BudgetExceededError, BudgetTracker, _current_month


def test_accumulates_cost(settings_factory):
    bt = BudgetTracker(settings_factory(monthly_budget_usd=50.0))
    bt.record_cost(1.0)
    bt.record_cost(2.5)
    assert bt.spent_this_month() == pytest.approx(3.5)


def test_check_allowed_under_budget(settings_factory):
    bt = BudgetTracker(settings_factory(monthly_budget_usd=10.0))
    bt.record_cost(2.0)
    allowed, ratio = bt.check_allowed()
    assert allowed is True
    assert ratio == pytest.approx(0.2)


def test_warn_does_not_block(settings_factory, caplog):
    bt = BudgetTracker(settings_factory(monthly_budget_usd=10.0, budget_warn_ratio=0.8))
    bt.record_cost(8.5)  # 85% > warn
    allowed, ratio = bt.check_allowed()
    assert allowed is True
    assert ratio == pytest.approx(0.85)


def test_hard_stop_at_100pct(settings_factory):
    bt = BudgetTracker(settings_factory(monthly_budget_usd=5.0))
    bt.record_cost(5.0)
    with pytest.raises(BudgetExceededError):
        bt.check_allowed()


def test_unknown_cost_not_counted(settings_factory):
    bt = BudgetTracker(settings_factory(monthly_budget_usd=5.0))
    bt.record_cost(None)
    assert bt.spent_this_month() == 0.0


def test_negative_cost_rejected(settings_factory):
    bt = BudgetTracker(settings_factory())
    with pytest.raises(ValueError):
        bt.record_cost(-1.0)


def test_corrupt_budget_file_raises(settings_factory):
    settings = settings_factory(monthly_budget_usd=5.0)
    bt = BudgetTracker(settings)
    path = settings.data_dir / "budget" / f"budget-{_current_month()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Cannot read budget"):
        bt.spent_this_month()


def test_month_isolation(settings_factory):
    # A file for a different month must not count toward this month.
    settings = settings_factory(monthly_budget_usd=50.0)
    bt = BudgetTracker(settings)
    other = settings.data_dir / "budget" / "budget-2000-01.json"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(json.dumps({"month": "2000-01", "total_usd": 999.0}), encoding="utf-8")
    assert bt.spent_this_month() == 0.0
