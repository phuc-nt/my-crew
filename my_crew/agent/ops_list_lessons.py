"""Read-only view of what the coordinator learned from finished work: `list_lessons`.

The reflection pass (v68) writes a lesson after a team task ends badly, but until now
nothing showed them to the CEO — the whole point of learning from a stall is that a
human can see, and disagree with, what was learned.

Two things this module refuses to guess:

1. **Whose memory to read.** Lessons live under the agent that runs the team tick, which
   is `company.coordinator_id` — NOT whoever is chatting. Reading the chatting agent's
   namespace would show an empty list to a CEO talking to the secretary while the
   coordinator has been learning all along.
2. **Which rows are lessons.** They share both a namespace and a `{"fact","ts"}` shape
   with the ordinary facts `memory_node` remembers from reports, so "has a fact" would
   sweep up chat memory and present it as something learned from a task. The reflection
   writer tags its rows `source: "reflection"` and this filters on exactly that.

Consequence of filtering at the source: lessons written BEFORE the tag shipped carry no
`source` and will not appear here. Left alone deliberately — backfilling would have to
guess which untagged rows were lessons, and the set refills itself as tasks finish.
"""

from __future__ import annotations

#: Newest lessons only. The list is a nudge in a chat window, not an archive; the memory
#: view in the cockpit is where the full set belongs.
MAX_LESSONS = 15


def run_list_lessons(slots: dict[str, str]) -> str:
    from my_crew.agent.memory_node import _NAMESPACE_KIND
    from my_crew.agent.store import get_store
    from my_crew.agent.task_reflection import SOURCE_REFLECTION
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.company import load_company

    coordinator_id = load_company().coordinator_id
    if not coordinator_id:
        return "Chưa cấu hình agent điều phối nên chưa có bài học nào được ghi."

    try:
        settings = load_profile(
            coordinator_id, data_dir=agent_data_dir(coordinator_id)
        ).settings
    except Exception:
        raise ValueError(f"không tải được hồ sơ điều phối '{coordinator_id}'.") from None

    store = get_store(settings)
    try:
        items = store.search((coordinator_id, _NAMESPACE_KIND), limit=MAX_LESSONS)
    finally:
        _close_store(store)

    lessons = [
        item.value.get("fact")
        for item in items
        if (item.value or {}).get("source") == SOURCE_REFLECTION
        and (item.value or {}).get("fact")
    ]
    if not lessons:
        return "Chưa học được gì từ các việc đã giao."
    return "\n".join(["Bài học rút ra từ các việc đã giao:",
                      *(f"- {text}" for text in lessons)])


def _close_store(store) -> None:
    """Close the Store's connection if it has one (sqlite, Postgres); no-op in-memory."""
    conn = getattr(store, "conn", None)
    if conn is not None and hasattr(conn, "close"):
        conn.close()
