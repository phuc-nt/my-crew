"""The scenario cast: real `LoadedProfile` objects built through the REAL config
builders, plus the registry/company doubles that make them a company.

One admin agent is the CEO's Telegram gateway (ops operator), one coordinator
runs the team tick, and a small bench of workers takes the steps. All settings
route into the harness tmp data dir; the OpenRouter key is a dummy because the
LLM rung is class-patched to ScriptedLlm before any call can leave the process.
"""

from __future__ import annotations

from pathlib import Path

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.config.config_builders_reporting import build_reporting_config_from_dict
from my_crew.profile.loader import LoadedProfile
from my_crew.runtime.company import Company
from my_crew.runtime.registry import RegistryEntry

#: Env var holding the (dummy) bot token — resolved at send time by the transport,
#: whose HTTP call is captured before any network use.
BOT_TOKEN_ENV = "FULLFLOW_BOT_TOKEN"
#: Telegram private chat: chat_id == the CEO's user id.
CEO_CHAT_ID = "990001"

ADMIN_ID = "admin"
COORDINATOR_ID = "coordinator"
#: Assignable workers (id, domain). Kept tiny: enough for a 3-step DAG with
#: distinct owners. Domains must exist as shipped domain packs.
WORKERS: tuple[tuple[str, str], ...] = (
    ("secretary", "pm"),
    ("analyst", "pm"),
    ("writer", "pm"),
)


def make_company(*, autopilot: bool = False, auto_confirm: bool = False) -> Company:
    return Company(
        name="Cty Fullflow", coordinator_id=COORDINATOR_ID, team_task_cap_usd=5.0,
        team_task_auto_confirm=auto_confirm, autopilot=autopilot,
    )


def make_registry() -> tuple[RegistryEntry, ...]:
    ids = [ADMIN_ID, COORDINATOR_ID, *(w for w, _ in WORKERS)]
    return tuple(RegistryEntry(id=i, enabled=True) for i in ids)


def _settings(data_dir: Path):
    return build_settings_from_dict({
        "openrouter_api_key": "scripted-key",
        "data_dir": data_dir,
        "dry_run": False,
    })


def _config(*, with_telegram: bool):
    d: dict = {
        "jira_project_key": "FF",
        "github_repo": "org/repo",
        "slack_report_channel": "C_REP",
        "slack_stakeholder_channel": "",
        "slack_external_channels": "",
    }
    if with_telegram:
        d["telegram"] = {
            "bot_token_env": BOT_TOKEN_ENV,
            "chat_ids": [CEO_CHAT_ID],
            "poll_minutes": 5,
            "ops_operator_id": CEO_CHAT_ID,
        }
    return build_reporting_config_from_dict(d)


def make_profile(profile_id: str, *, domain: str, data_dir: Path) -> LoadedProfile:
    """A real LoadedProfile. The admin agent alone carries the Telegram block —
    it is the CEO's ops gateway; workers/coordinator never talk to the CEO chat
    directly (operator notify resolves through the admin profile)."""
    # Admin polls the CEO chat; the coordinator shares the bot SEND-ONLY (the
    # ✅ done fast path + escalation resolve telegram from the tick's profile).
    is_admin = profile_id in (ADMIN_ID, COORDINATOR_ID)
    return LoadedProfile(
        profile_id=profile_id,
        name=profile_id,
        enabled=True,
        settings=_settings(data_dir),
        config=_config(with_telegram=is_admin),
        soul=f"Bạn là {profile_id} trong một công ty agent thử nghiệm.",
        project="",
        memory="",
        schedule={},
        reports=(),
        domain=domain,
    )


def make_cast(data_dir: Path) -> dict[str, LoadedProfile]:
    """{agent_id: LoadedProfile} for every registry agent."""
    cast = {
        ADMIN_ID: make_profile(ADMIN_ID, domain="admin", data_dir=data_dir),
        COORDINATOR_ID: make_profile(COORDINATOR_ID, domain="pm", data_dir=data_dir),
    }
    for worker_id, domain in WORKERS:
        cast[worker_id] = make_profile(worker_id, domain=domain, data_dir=data_dir)
    return cast
