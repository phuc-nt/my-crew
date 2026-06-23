"""Shared test fixtures. Tests never touch the real .data/ dir or real env."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.settings import Settings


@pytest.fixture
def settings_factory(tmp_path: Path):
    """Return a builder for Settings pinned to an isolated tmp data dir.

    Routes through `build_settings_from_dict` (the real builder) so the fixture
    cannot drift from production coercion/defaults — only the data dir and the
    explicit test overrides differ from a real build.
    """
    from src.config.config_builders import build_settings_from_dict

    def _make(
        *,
        dry_run: bool = True,
        write_disabled: bool = False,
        api_key: str | None = None,
        monthly_budget_usd: float = 50.0,
        budget_warn_ratio: float = 0.8,
    ) -> Settings:
        return build_settings_from_dict(
            {
                "openrouter_api_key": api_key,
                "openrouter_model": "test/model",
                "openrouter_referer": "http://test",
                "openrouter_title": "test",
                "dry_run": dry_run,
                "write_disabled": write_disabled,
                "monthly_budget_usd": monthly_budget_usd,
                "budget_warn_ratio": budget_warn_ratio,
                "data_dir": tmp_path,
            }
        )

    return _make
