"""Company identity — greenfield `company.yaml` at repo root.

Mirrors `registry.py`'s load shape (dataclass + yaml.safe_load) but is DEGRADE-NOT-RAISE:
`registry.yaml` must exist (bootstrapped from its example since v18) for the service
to know which agents to run, but a missing
`company.yaml` is not a run-blocking condition — a fresh install has no company set up
yet, and every reader (Setup wizard, dashboard header) must render a safe default instead
of 500ing. Writes go through `save_company`, which mirrors `registry_edit`'s
validate-before-replace + atomic temp-then-rename pattern under the same style of
process-wide lock. `save_company` is a ruamel.yaml round-trip load-modify-save (v88
P5-D0, same sanctioned pattern as `my_crew.server.profile_patch`): it preserves any
hand-written key and comment already in company.yaml, only touching the 6 known
fields — it no longer rebuilds the document from a fixed dict.

Config-only: no secret ever belongs in this file (name + coordinator id + a cost cap).
"""

from __future__ import annotations

import io
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from my_crew.config.settings import MY_CREW_HOME

_COMPANY_PATH = MY_CREW_HOME / "company.yaml"

#: Default monthly cap for a cross-agent "team task" (Validation Session 1 decision).
DEFAULT_TEAM_TASK_CAP_USD = 2.0

#: Default number of team-task steps the coordinator ticker may dispatch CONCURRENTLY
#: for one task (v13 M34) — the ticker already dispatches across separate ticks (each
#: tick spawns at most `team_task_concurrency` NEW steps while under this many are
#: still `running`), this is the running-steps cap, not a per-tick spawn count cap.
DEFAULT_TEAM_TASK_CONCURRENCY = 2

#: One process-wide lock for every company.yaml write — same rationale as
#: `registry_edit._EDIT_LOCK`: the web admin routes run in a threadpool, so two
#: concurrent saves (double-submit) must not interleave read-modify-write.
_EDIT_LOCK = threading.Lock()


@dataclass(frozen=True)
class Company:
    """Company identity: display name, coordinator agent id, team-task cost cap +
    concurrency cap (+ v15 auto-confirm flag)."""

    name: str
    coordinator_id: str | None
    team_task_cap_usd: float
    team_task_concurrency: int = DEFAULT_TEAM_TASK_CONCURRENCY
    # v15 (Decision Q1): True ⇒ a decomposed team-task plan is confirmed IMMEDIATELY
    # after preview with the same hash-bind path the CEO's manual confirm uses — only
    # who presses the button changes, never the bind/audit trail. Default False: the
    # CEO reviews every plan, byte-compatible with pre-v15 behavior.
    team_task_auto_confirm: bool = False
    # v63 autopilot (explicit CEO decision 2026-08-04, "Toàn quyền thật"): True ⇒ the
    # secretary decides in the CEO's place — plans auto-confirm, stalled tasks
    # auto-resolve (autopilot_sweep), pending Lớp B approvals auto-approve. Every
    # decision is audited + reported back; Lớp A hard-denies and cost caps are NOT
    # affected (structural, checked before any gate this flag touches). Per-task
    # opt-out: `team_tasks.require_ceo_approval`. Default False.
    autopilot: bool = False


def load_company(path: Path | None = None) -> Company:
    """Load `company.yaml`, degrading to a safe default instead of raising.

    Missing file, unreadable YAML, or a malformed shape all yield the same safe default
    (`name=""`, `coordinator_id=None`, `team_task_cap_usd=DEFAULT_TEAM_TASK_CAP_USD`) —
    company identity is cosmetic/config, never a hard dependency for the service to run.
    """
    company_path = path if path is not None else _COMPANY_PATH
    try:
        raw = company_path.read_text(encoding="utf-8")
    except OSError:
        return _default_company()

    try:
        doc = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return _default_company()
    if not isinstance(doc, dict):
        return _default_company()

    name = doc.get("name")
    name = str(name) if isinstance(name, str) else ""

    raw_coordinator_id = doc.get("coordinator_id")
    coordinator_id = (
        str(raw_coordinator_id)
        if isinstance(raw_coordinator_id, str) and raw_coordinator_id.strip()
        else None
    )

    cap = doc.get("team_task_cap_usd")
    try:
        team_task_cap_usd = float(cap) if cap is not None else DEFAULT_TEAM_TASK_CAP_USD
    except (TypeError, ValueError):
        team_task_cap_usd = DEFAULT_TEAM_TASK_CAP_USD

    concurrency = doc.get("team_task_concurrency")
    try:
        team_task_concurrency = (
            int(concurrency) if concurrency is not None else DEFAULT_TEAM_TASK_CONCURRENCY
        )
    except (TypeError, ValueError):
        team_task_concurrency = DEFAULT_TEAM_TASK_CONCURRENCY
    if team_task_concurrency < 1:
        team_task_concurrency = DEFAULT_TEAM_TASK_CONCURRENCY

    team_task_auto_confirm = bool(doc.get("team_task_auto_confirm", False) is True)
    autopilot = bool(doc.get("autopilot", False) is True)

    return Company(
        name=name, coordinator_id=coordinator_id, team_task_cap_usd=team_task_cap_usd,
        team_task_concurrency=team_task_concurrency,
        team_task_auto_confirm=team_task_auto_confirm,
        autopilot=autopilot,
    )


def _default_company() -> Company:
    return Company(
        name="", coordinator_id=None, team_task_cap_usd=DEFAULT_TEAM_TASK_CAP_USD,
        team_task_concurrency=DEFAULT_TEAM_TASK_CONCURRENCY,
    )


def _ruamel_yaml() -> YAML:
    # round_trip preserves comments/key-order/quote-style — same config as
    # `profile_patch._yaml()`, the sanctioned pattern this mirrors.
    y = YAML(typ="rt")
    y.default_flow_style = False
    y.preserve_quotes = True
    return y


def save_company(
    name: str,
    coordinator_id: str | None,
    team_task_cap_usd: float = DEFAULT_TEAM_TASK_CAP_USD,
    team_task_concurrency: int = DEFAULT_TEAM_TASK_CONCURRENCY,
    team_task_auto_confirm: bool = False,
    autopilot: bool = False,
    *,
    path: Path | None = None,
) -> None:
    """Load-modify-save write of `company.yaml`, atomic (temp-then-rename) under the
    process lock.

    v88 P5-D0: rewritten from a fixed-6-key rebuild (which silently erased any
    hand-written key not in that set — same incident class `profile_patch` was built
    to avoid for profile.yaml) to a ruamel.yaml round-trip load-modify-save. Only the
    6 known fields below are written; every other top-level key and comment already in
    the file survives untouched. A missing/unreadable/non-mapping existing file starts
    from an empty document (mirrors `load_company`'s degrade-not-raise posture).

    Validate-before-replace: the new document is round-tripped through `load_company` on
    the temp file before the real file is replaced, so a value that can't be read back
    correctly never lands (mirrors `registry_edit._replace_validated`).
    """
    company_path = path if path is not None else _COMPANY_PATH
    values = {
        "name": str(name or ""),
        "coordinator_id": str(coordinator_id) if coordinator_id else None,
        "team_task_cap_usd": float(team_task_cap_usd),
        "team_task_concurrency": int(team_task_concurrency),
        "team_task_auto_confirm": bool(team_task_auto_confirm),
        "autopilot": bool(autopilot),
    }

    ryaml = _ruamel_yaml()
    with _EDIT_LOCK:
        try:
            raw = company_path.read_text(encoding="utf-8")
        except OSError:
            raw = None

        doc = None
        if raw is not None:
            try:
                doc = ryaml.load(raw)
            except Exception:  # noqa: BLE001 — malformed existing file degrades to fresh doc
                doc = None
        if not isinstance(doc, dict):
            doc = CommentedMap()

        for key, value in values.items():
            doc[key] = value

        buf = io.StringIO()
        ryaml.dump(doc, buf)
        text = buf.getvalue()

        tmp = company_path.with_suffix(company_path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        try:
            loaded = load_company(tmp)
            if (
                loaded.name != values["name"]
                or loaded.coordinator_id != values["coordinator_id"]
                or loaded.team_task_cap_usd != values["team_task_cap_usd"]
                or loaded.team_task_concurrency != values["team_task_concurrency"]
                or loaded.team_task_auto_confirm != values["team_task_auto_confirm"]
                or loaded.autopilot != values["autopilot"]
            ):
                raise RuntimeError("company.yaml write did not round-trip the expected values")
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, company_path)
