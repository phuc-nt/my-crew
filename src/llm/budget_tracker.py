"""Monthly OpenRouter spend cap (PDR §7.8).

Accumulates USD cost per calendar month in a JSON file under the data dir.
Warns at `budget_warn_ratio` (default 80%), hard-stops at 100% by raising
`BudgetExceededError` from `check_allowed()`. Rolls over automatically: a new
month uses a fresh file, so the running total resets.

Lives in the llm/ layer because it gates LLM calls. It does NOT import agent/ or
actions/. An autonomous loop with a bug can burn money fast, so this cap is a
hard requirement, not advisory.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from src.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when the monthly budget is fully spent and a new call is blocked."""


def _current_month() -> str:
    """UTC year-month key, e.g. '2026-06'. UTC avoids local-tz rollover ambiguity."""
    return datetime.now(UTC).strftime("%Y-%m")


class BudgetTracker:
    """File-backed monthly cost accumulator."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._budget_dir = self._settings.data_dir / "budget"

    def _path_for(self, month: str) -> Path:
        return self._budget_dir / f"budget-{month}.json"

    def _read(self, month: str) -> float:
        path = self._path_for(month)
        if not path.exists():
            return 0.0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return float(data.get("total_usd", 0.0))
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            # Corrupt budget file must not silently reset the cap to zero;
            # surface it so a human notices rather than over-spending.
            raise RuntimeError(f"Cannot read budget file {path}: {exc}") from exc

    def _write(self, month: str, total: float) -> None:
        path = self._path_for(month)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"month": month, "total_usd": round(total, 6)}
        path.write_text(json.dumps(payload), encoding="utf-8")

    def spent_this_month(self) -> float:
        return self._read(_current_month())

    def check_allowed(self) -> tuple[bool, float]:
        """Return (allowed, ratio_spent). Raise BudgetExceededError at >=100%.

        Call this BEFORE an LLM request. Warns (logs) once spending crosses the
        warn ratio so the operator gets a heads-up before the hard stop.
        """
        cap = self._settings.monthly_budget_usd
        spent = self.spent_this_month()
        ratio = spent / cap if cap > 0 else 0.0

        if ratio >= 1.0:
            raise BudgetExceededError(
                f"Monthly OpenRouter budget ${cap:.2f} reached "
                f"(spent ${spent:.4f}). New LLM calls blocked until next month."
            )
        if ratio >= self._settings.budget_warn_ratio:
            logger.warning(
                "OpenRouter spend at %.0f%% of $%.2f cap (spent $%.4f).",
                ratio * 100,
                cap,
                spent,
            )
        return True, ratio

    def record_cost(self, usd: float | None) -> None:
        """Add a request's cost to this month's total. Call AFTER an LLM request.

        Unknown cost (None) records nothing — the per-call cost could not be
        determined. This is logged so unknown-cost runs are visible (the budget
        cannot protect against costs it cannot see).
        """
        if usd is None:
            logger.warning("LLM call cost unknown; not counted toward budget.")
            return
        if usd < 0:
            raise ValueError(f"Cost cannot be negative: {usd}")
        month = _current_month()
        self._write(month, self._read(month) + usd)
