"""Chat-ops commands over the secretary's heartbeat (v68) — scratch list + re-enable.

Three commands, all aimed at the heartbeat store of the agent that OWNS the pulse:

- `add_heartbeat_watch` — "để ý giùm X". The system has no column for X, so it stores the
  CEO's own words and echoes them back on a slow cadence. It never claims to know X's
  status; inventing one would be worse than staying silent.
- `stop_heartbeat_watch` — "thôi khỏi để ý X".
- `enable_heartbeat` — turn the pulse back on after it disabled itself. Chat is the only
  re-enable path on purpose: the CEO lives in Telegram, and requiring a terminal would
  mean a broken heartbeat stays broken until someone opens a laptop.

The heartbeat is a `personal`-domain feature, so these resolve the personal agent from the
registry rather than making the CEO type an agent id for the assistant they are already
talking to. With several personal agents the id is asked for, since guessing would silently
edit the wrong secretary's list.
"""

from __future__ import annotations

from pathlib import Path


class NoHeartbeatAgentError(ValueError):
    """Raised with a CEO-facing message when the target agent cannot be resolved."""


def _heartbeat_agents() -> list[str]:
    """Ids of registry agents whose profile actually configures a heartbeat."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.registry import load_registry

    out: list[str] = []
    for entry in load_registry():
        try:
            loaded = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
        except Exception:  # noqa: BLE001 — a broken profile must not hide the others
            continue
        if getattr(loaded, "heartbeat_every_minutes", None):
            out.append(entry.id)
    return out


def _resolve_agent(slots: dict[str, str]) -> str:
    """The agent whose heartbeat this command targets."""
    explicit = (slots.get("agent_id") or "").strip()
    if explicit:
        return explicit
    agents = _heartbeat_agents()
    if not agents:
        raise NoHeartbeatAgentError("chưa có agent nào bật nhịp thư ký")
    if len(agents) > 1:
        raise NoHeartbeatAgentError(
            "có nhiều agent bật nhịp thư ký (" + ", ".join(agents) + "), "
            "bạn nhắn rõ agent nào giúp mình"
        )
    return agents[0]


def _open_store(agent_id: str):
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.heartbeat_state_store import HeartbeatStateStore, heartbeat_db_path

    return HeartbeatStateStore(heartbeat_db_path(Path(agent_data_dir(agent_id))))


def run_add_heartbeat_watch(slots: dict[str, str]) -> str:
    agent_id = _resolve_agent(slots)
    text = (slots.get("text") or "").strip()
    if not text:
        raise ValueError("bạn muốn mình để ý việc gì?")
    store = _open_store(agent_id)
    try:
        store.add_scratch(text)
    finally:
        store.close()
    # Says exactly what it will do — a reminder — so the CEO never expects a status report
    # on something the system cannot observe.
    return f"Được, mình sẽ nhắc bạn định kỳ về: “{text}”."


def preview_add_heartbeat_watch(slots: dict[str, str]) -> str:
    return (f"Mình sẽ ghi vào danh sách để ý: “{(slots.get('text') or '').strip()}” "
            "và nhắc bạn định kỳ (mỗi 24h một lần).\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


def run_stop_heartbeat_watch(slots: dict[str, str]) -> str:
    agent_id = _resolve_agent(slots)
    text = (slots.get("text") or "").strip()
    store = _open_store(agent_id)
    try:
        items = store.list_scratch()
        matched = _match_scratch(items, text)
        if matched is None:
            listing = "; ".join(f"“{i['text']}”" for i in items) or "(trống)"
            raise ValueError(f"không thấy việc nào khớp “{text}”. Đang để ý: {listing}")
        store.remove_scratch(matched["id"])
    finally:
        store.close()
    return f"Rồi, mình thôi không nhắc về “{matched['text']}” nữa."


def _match_scratch(items: list[dict], text: str) -> dict | None:
    """Find the item the CEO means. Exact match first, then a containment match — the CEO
    says "thôi khỏi để ý hợp đồng", not the full sentence they typed a week ago."""
    needle = text.casefold().strip()
    if not needle:
        return None
    for item in items:
        if item["text"].casefold().strip() == needle:
            return item
    hits = [i for i in items if needle in i["text"].casefold()]
    return hits[0] if len(hits) == 1 else None


def preview_stop_heartbeat_watch(slots: dict[str, str]) -> str:
    return (f"Mình sẽ bỏ “{(slots.get('text') or '').strip()}” khỏi danh sách để ý.\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


def run_enable_heartbeat(slots: dict[str, str]) -> str:
    agent_id = _resolve_agent(slots)
    store = _open_store(agent_id)
    try:
        if not store.is_disabled():
            return "Nhịp thư ký đang chạy bình thường, không cần bật lại."
        # `enable()` also clears the failure streak: leaving it at the limit would let the
        # very next hiccup re-disable the pulse immediately.
        store.enable()
    finally:
        store.close()
    return "Đã bật lại nhịp thư ký. Mình sẽ ngó việc như cũ và chỉ nhắn khi có việc cần bạn."


def preview_enable_heartbeat(slots: dict[str, str]) -> str:
    return ("Mình sẽ bật lại nhịp thư ký chủ động (đang tắt do gửi hụt nhiều lần).\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")
