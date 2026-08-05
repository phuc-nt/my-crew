"""The `secretary-heartbeat` pseudo-kind body (v68) — the secretary's proactive pulse.

One pulse: build a digest by SQL; if nothing needs the CEO, return silently having spent
zero tokens. Only a non-empty digest is worth a model call, and even then the model may
answer with the ack token to say "not worth sending" — two independent chances to stay
quiet, because a proactive channel that cries wolf gets muted and then it protects nobody.

Order of the gates, each one cheaper than the next:
1. transport configured?         (no CEO DM ⇒ nothing to send)
2. writes enabled?               (kill-switch)
3. digest non-empty?             (SQL only — the common case exits here, free)
4. any problem not yet raised?   (per-item — old news stays quiet, a new item speaks)
5. mid-conversation?             (defer rather than interrupt the CEO mid-sentence)
6. model says it is worth it?    (ack token / too-short reply ⇒ drop)

The heartbeat only ever REPORTS. It never assigns work, creates reminders, or moves a
task — a proactive loop with write authority can amplify its own mistakes, so the
authority simply is not wired here.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The model emits this alone when the digest does not warrant waking the CEO.
HEARTBEAT_ACK = "HEARTBEAT_OK"

#: After stripping the ack token, a remainder this short carries no information — treat
#: it as a no-op rather than sending the CEO a fragment.
HEARTBEAT_SUPPRESS_MAX_CHARS = 300


def _quiet(status: str, checked: int = 0) -> dict:
    """The run-event dict every generic kind returns. A quiet pulse is a SUCCESS."""
    return {"status": status, "checked": checked, "cost_usd": None, "delivered": False}


def run_secretary_heartbeat(loaded: Any, settings: Any) -> dict:
    """One heartbeat pulse. Only a blown monthly cap escapes (the worker records it as an
    error run); every other failure degrades to a status the worker records normally.

    Wraps `_pulse` purely to keep the health bookkeeping in one place: three failed runs
    back to back disable the pulse and tell the CEO once, because a proactive channel that
    is broken should go quiet and say so rather than keep failing on a timer forever.
    """
    agent_id = getattr(loaded, "profile_id", "")
    try:
        result = _pulse(loaded, settings)
    except Exception:
        # The cap (and anything else fatal) still propagates to the worker, but a broken
        # pulse counts toward the disable streak on its way out.
        _record_health(loaded, settings, agent_id, failed=True)
        raise
    _record_health(loaded, settings, agent_id, failed=result["status"] == "send_failed")
    return result


def _pulse(loaded: Any, settings: Any) -> dict:
    """The pulse itself — every gate in order. See the module docstring."""
    from my_crew.runtime.secretary_heartbeat_digest import (
        build_digest,
        format_digest,
        load_reported,
        save_reported,
        unreported,
    )

    agent_id = getattr(loaded, "profile_id", "")
    telegram = getattr(getattr(loaded, "config", None), "telegram", None)
    operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
    if not telegram or not operator:
        return _quiet("no_operator")  # no CEO DM configured — not an error
    if getattr(settings, "write_disabled", False):
        return _quiet("writes_disabled")

    digest = build_digest(agent_id)
    checked = (len(digest.stalled) + len(digest.undelivered)
               + len(digest.reminders) + len(digest.stale_drafts))
    live = set(digest.item_keys())
    reported = load_reported(agent_id)
    if digest.errors:
        # Logged on EVERY path, not just the quiet one: a store that breaks while other
        # problems exist would otherwise leave no trace at all, and "all clear" would be
        # indistinguishable from "half the signals never got read".
        logger.warning("heartbeat %s: signals unreadable: %s", agent_id, digest.errors)
    # Pruning means "this problem is gone". An unreadable store proves no such thing — it
    # returns an empty signal, so pruning on it would forget live problems and then
    # re-announce every one of them the moment the store recovers. A DB blip must not
    # become a DM storm, so keep the old state whole and let the next clean pulse prune.
    keep = live if not digest.errors else live | reported
    if not digest:
        # The whole point: a quiet system costs nothing. No LLM call happens here.
        # Still prune: every previously-reported problem is gone, so nothing stays
        # remembered. Otherwise a problem that resolves and later RECURS would match its
        # stale entry and be silently swallowed forever.
        if reported:
            save_reported(agent_id, keep)
        return _quiet("quiet")

    fresh = unreported(digest, reported)
    if not fresh:
        # Every problem here has already been raised. Prune resolved entries so their
        # recurrence counts as new, then stay quiet without paying for a model call.
        if reported != keep:
            save_reported(agent_id, keep)
        return _quiet("unchanged", checked)

    if _is_mid_conversation(agent_id):
        _audit_deferred(loaded, settings, agent_id, reason="operator mid-conversation")
        return _quiet("deferred", checked)

    # The message covers the whole live picture, but only `fresh` decides whether to
    # speak — the CEO gets full context without being re-pinged for old news.
    text = format_digest(digest)
    # A scratch item among the FRESH keys means the CEO asked to be reminded now, which
    # is an instruction rather than something for the model to weigh. System-detected
    # problems keep the suppression licence exactly as before.
    scratch_is_fresh = any(k.startswith("scratch:") for k in fresh)
    message, cost_usd = _compose(settings, text, may_suppress=not scratch_is_fresh)
    # Newly-raised problems become "told"; anything that resolved since the last pulse is
    # forgotten so it can speak up again if it returns.
    if message is None:
        # Model judged it not worth sending. Record it anyway so the same unchanged
        # situation does not pay for another model call next pulse.
        save_reported(agent_id, keep)
        return {"status": "suppressed", "checked": checked, "cost_usd": cost_usd,
                "delivered": False}

    delivered = _send(loaded, settings, telegram, operator, message, fresh)
    if delivered:
        save_reported(agent_id, keep)
        # Only a message that actually reached the CEO consumes a scratch echo. Marking
        # earlier would burn the reminder on a pulse nobody ever saw.
        _mark_echoed(agent_id, digest)
    return {"status": "delivered" if delivered else "send_failed", "checked": checked,
            "cost_usd": cost_usd, "delivered": delivered}


def _mark_echoed(agent_id: str, digest: Any) -> None:
    """Start each echoed scratch item's next quiet window."""
    if not digest.scratch:
        return
    from datetime import UTC, datetime

    from my_crew.runtime.secretary_heartbeat_digest import open_state

    try:
        store = open_state(agent_id)
    except Exception:  # noqa: BLE001 — a missed mark costs one repeat, not the pulse
        logger.warning("heartbeat %s: could not mark scratch echoes", agent_id)
        return
    try:
        store.mark_scratch_echoed([s["id"] for s in digest.scratch], now=datetime.now(UTC))
    finally:
        store.close()


def _record_health(loaded: Any, settings: Any, agent_id: str, *, failed: bool) -> None:
    """Track consecutive failures and disable the pulse once it is clearly broken.

    The disable lives in the heartbeat store, not the CEO's `profile.yaml`: rewriting that
    file would destroy their comments, and the store is read fresh on every tick so the
    schedule stops without a restart. The CEO turns it back on from chat.
    """
    from my_crew.runtime.heartbeat_state_store import MAX_CONSECUTIVE_FAILURES
    from my_crew.runtime.secretary_heartbeat_digest import open_state

    try:
        store = open_state(agent_id)
    except Exception:  # noqa: BLE001 — health bookkeeping must never break the pulse
        logger.warning("heartbeat %s: could not record health", agent_id)
        return
    try:
        if not failed:
            store.record_success()
            return
        streak = store.record_failure()
        if streak < MAX_CONSECUTIVE_FAILURES or store.is_disabled():
            return  # not broken yet, or already told them once
        reason = f"{streak} nhịp liên tiếp gửi hụt"
        store.disable(reason)
    finally:
        store.close()
    _announce_disabled(loaded, settings, agent_id, reason)


def _announce_disabled(loaded: Any, settings: Any, agent_id: str, reason: str) -> None:
    """Tell the CEO ONCE that the pulse turned itself off, and how to turn it back on.

    Deliberately not via `_send`: that path just failed three times in a row, so this goes
    through the shared operator-notify helper instead. If it also fails, the disable still
    stands — a silent-but-off heartbeat beats one that keeps failing every 30 minutes.
    """
    from my_crew.runtime.operator_notify import notify_operator_best_effort

    try:
        notify_operator_best_effort(
            f"⚠️ Nhịp thư ký tự tắt sau {reason}. Nhắn “bật lại nhịp thư ký” khi muốn dùng lại.",
            dedup_hint=f"heartbeat-disabled:{agent_id}",
            rationale="secretary heartbeat: self-disabled after repeated failures",
        )
    except Exception:  # noqa: BLE001 — the disable matters more than the announcement
        logger.warning("heartbeat %s: could not announce self-disable", agent_id)


def _is_mid_conversation(agent_id: str, *, now: float | None = None) -> bool:
    """True when the operator has a LIVE ops draft — the CEO is mid-sentence with the
    secretary, and a proactive nudge would collide with their own dialogue.

    Bounded by the same `DRAFT_TTL_S` the store itself enforces in `load()`. Without that
    bound an abandoned half-typed command would defer the heartbeat forever: the row never
    goes away on its own, so "the CEO is still typing" would be true for all time.
    """
    import sqlite3
    import time

    from my_crew.agent.ops_conversation_store import DRAFT_TTL_S
    from my_crew.runtime.agent_paths import agent_data_dir

    db = agent_data_dir(agent_id) / "ops_conversation.sqlite3"
    if not db.exists():
        return False
    cutoff = (time.time() if now is None else now) - DRAFT_TTL_S
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT 1 FROM ops_drafts WHERE phase = 'collecting' AND updated_at > ? LIMIT 1",
            (cutoff,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def _compose(settings: Any, digest_text: str,
             *, may_suppress: bool = True) -> tuple[str | None, float | None]:
    """One isolated model turn: no conversation history, a fixed narrow prompt, and an
    explicit licence to answer with the ack token. Returns (message, cost) where a None
    message means stay silent.

    `may_suppress=False` takes that licence away. The model judges whether a SYSTEM-
    detected problem is worth the CEO's attention, but a scratch item is not a judgment
    call — the CEO asked to be reminded, so dropping it would be overriding a standing
    instruction with a guess. Verified against the live model: a scratch-only digest was
    answered with the ack token every time, silently swallowing the reminder.

    On a model failure the raw digest is sent instead of nothing: the digest was built
    from real rows, so the CEO still gets the facts even when phrasing is unavailable.
    A blown monthly cap is the one exception — it propagates, because "the agent is out of
    budget" is a real condition the worker must record, not something to paper over by
    quietly continuing to send.
    """
    licence = (
        f"Nếu không đáng làm phiền, chỉ trả lời đúng một từ: {HEARTBEAT_ACK}\n"
        if may_suppress else
        "CEO đã dặn nhắc lại những việc này, nên PHẢI nhắn — không được bỏ qua.\n"
    )
    prompt = (
        "Bạn là thư ký riêng. Dưới đây là những việc cần chú ý (phần 📌 là việc chính "
        "CEO dặn để ý — chỉ nhắc lại, KHÔNG suy đoán tình trạng).\n"
        "Nếu đáng báo cho CEO, viết MỘT tin nhắn tiếng Việt thật ngắn "
        "(tối đa 4 dòng), nêu đúng việc cần CEO quyết.\n"
        f"{licence}\n"
        f"{digest_text}"
    )
    from my_crew.llm.budget_tracker import BudgetExceededError

    try:
        reply, cost = _model_turn(settings, prompt)
    except BudgetExceededError:
        raise  # the cap is supreme (PDR §7.8) — never fall back past it
    except Exception:  # noqa: BLE001 — phrasing is a nicety; the facts still matter
        logger.exception("heartbeat: compose turn failed; sending raw digest")
        return digest_text, None
    if not reply:
        return digest_text, cost

    # Strip the ack token wherever the model put it, then judge what is left. The token
    # must actually be present to suppress — a merely short reply is still a real answer.
    remainder = reply.replace(HEARTBEAT_ACK, "").strip()
    if HEARTBEAT_ACK in reply and len(remainder) <= HEARTBEAT_SUPPRESS_MAX_CHARS:
        if not may_suppress:
            # The model emitted the token even though it was told not to. The CEO's
            # standing instruction outranks the model's judgment, so fall back to the
            # raw digest rather than swallowing a reminder they asked for.
            return digest_text, cost
        return None, cost
    return (remainder or digest_text), cost


def _model_turn(settings: Any, prompt: str) -> tuple[str | None, float | None]:
    """Single-shot completion with NO conversation history — one user message, nothing
    else. Returns (content, cost_usd). Cost flows into the same budget tracker every
    other call uses, so a heartbeat can never spend past the monthly cap."""
    from my_crew.llm.client import LlmClient

    result = LlmClient(settings).complete([{"role": "user", "content": prompt}])
    return result.content, result.cost_usd


def _send(loaded: Any, settings: Any, telegram: Any, operator: str, message: str,
          fresh: tuple[str, ...]) -> bool:
    """Deliver through the Action Gateway so Lớp A, the chat_ids allowlist and the secret
    scan all re-gate this message exactly like every other outbound Telegram send."""
    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.actions.telegram_write import send_telegram_message

    agent_id = getattr(loaded, "profile_id", "")
    gateway = ActionGateway(
        settings,
        external_channels=getattr(loaded.config, "slack_external_channels", frozenset()),
        actor=agent_id,
    )
    try:
        result = send_telegram_message(
            message,
            gateway=gateway,
            telegram=telegram,
            chat_id=operator,
            # Keyed on WHAT is wrong, so a crash-after-send retry is a clean no-op but a
            # genuinely new problem is never swallowed as a duplicate.
            dedup_hint=f"heartbeat:{agent_id}:{'|'.join(fresh)}",
            rationale="secretary heartbeat: proactive check-in",
        )
    except Exception:  # noqa: BLE001 — a failed pulse must not crash the worker
        logger.exception("heartbeat %s: send failed", agent_id)
        return False
    finally:
        gateway.close()
    return result.status in ("executed", "deduplicated")


def _audit_deferred(loaded: Any, settings: Any, agent_id: str, *, reason: str) -> None:
    """Record a skipped pulse so a heartbeat that never speaks is diagnosable."""
    from pathlib import Path

    from my_crew.audit.audit_log import AuditEntry, AuditLog

    try:
        AuditLog(Path(settings.data_dir) / "audit" / "audit.jsonl").record(
            AuditEntry(
                action_type="heartbeat", tool="heartbeat:secretary", verdict="skipped",
                reason=reason, actor=agent_id,
            )
        )
    except Exception:  # noqa: BLE001 — auditing a skip must never break the skip
        logger.warning("heartbeat %s: could not audit deferral", agent_id)
