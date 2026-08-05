"""v69 `list_lessons` — showing the CEO what the coordinator learned from finished work.

Two failure modes drive every test here, and both would be silent:

1. Reading the WRONG agent's memory. Lessons are written under the agent that runs the
   team tick, so reading whoever is chatting shows an empty list while the coordinator
   has been learning for weeks.
2. Showing memory that is NOT a lesson. Reflection rows and the facts `memory_node`
   remembers from reports share a namespace AND a shape, so an unfiltered read would
   present ordinary chat memory as something learned from a task.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from my_crew.agent.ops_list_lessons import run_list_lessons
from my_crew.agent.task_reflection import SOURCE_REFLECTION


class FakeStore:
    """Namespaced search, the only Store method this command uses."""

    def __init__(self, data: dict | None = None) -> None:
        self.data = data or {}
        self.searched: list[tuple] = []

    def search(self, namespace, limit=10):
        self.searched.append(namespace)
        rows = list(self.data.get(namespace, {}).items())[:limit]
        return [SimpleNamespace(key=k, value=v) for k, v in rows]


def _lesson(text):
    return {"fact": text, "ts": "2026-08-05T00:00:00+00:00", "source": SOURCE_REFLECTION}


def _plain_fact(text):
    """What `memory_node` writes: same namespace, same shape, no source tag."""
    return {"fact": text, "ts": "2026-08-05T00:00:00+00:00"}


@pytest.fixture()
def wired(monkeypatch):
    """Company names `coordinator`; profile loading and the Store are stubbed."""
    store = FakeStore()
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda *a, **k: SimpleNamespace(coordinator_id="coordinator"),
    )
    monkeypatch.setattr(
        "my_crew.profile.loader.load_profile",
        lambda *a, **k: SimpleNamespace(settings=SimpleNamespace(store="memory")),
    )
    monkeypatch.setattr("my_crew.agent.store.get_store", lambda settings: store)
    return store


def test_a_tagged_lesson_is_shown(wired):
    wired.data[("coordinator", "memory")] = {"k1": _lesson("Giao bước viết phải kèm tiêu chí.")}
    assert "Giao bước viết phải kèm tiêu chí." in run_list_lessons({})


def test_ordinary_remembered_facts_are_not_presented_as_lessons(wired):
    """The row shapes are identical — only the tag tells them apart, and getting this
    wrong would show the CEO their own chat memory as 'what we learned from a task'."""
    wired.data[("coordinator", "memory")] = {
        "k1": _lesson("Bước phụ thuộc nên nêu rõ đầu ra cần từ bước trước."),
        "k2": _plain_fact("CEO thích họp buổi sáng."),
    }
    reply = run_list_lessons({})
    assert "Bước phụ thuộc nên nêu rõ đầu ra cần từ bước trước." in reply
    assert "CEO thích họp buổi sáng." not in reply


def test_lessons_are_read_from_the_coordinator_not_the_chatting_agent(wired):
    """The command runs inside a chat with the secretary, but reflection writes under the
    coordinator — reading the caller's namespace would always look empty."""
    wired.data[("coordinator", "memory")] = {"k1": _lesson("Bài học của điều phối.")}
    wired.data[("secretary", "memory")] = {"k2": _lesson("Không được đọc từ đây.")}

    reply = run_list_lessons({})
    assert wired.searched == [("coordinator", "memory")]
    assert "Không được đọc từ đây." not in reply


def test_nothing_learned_yet_says_so_instead_of_inventing(wired):
    wired.data[("coordinator", "memory")] = {"k1": _plain_fact("CEO thích họp buổi sáng.")}
    assert run_list_lessons({}) == "Chưa học được gì từ các việc đã giao."


def test_an_empty_namespace_says_nothing_learned(wired):
    assert run_list_lessons({}) == "Chưa học được gì từ các việc đã giao."


def test_a_fleet_without_a_coordinator_says_so_rather_than_reading_a_guess(monkeypatch):
    """No coordinator configured means no team tick has ever run, so there is nothing to
    read — and no agent id to guess at."""
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda *a, **k: SimpleNamespace(coordinator_id=None),
    )
    assert "Chưa cấu hình agent điều phối" in run_list_lessons({})


def test_an_unloadable_coordinator_profile_is_a_clear_refusal(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("hồ sơ hỏng")

    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda *a, **k: SimpleNamespace(coordinator_id="coordinator"),
    )
    monkeypatch.setattr("my_crew.profile.loader.load_profile", _boom)
    with pytest.raises(ValueError, match="coordinator"):
        run_list_lessons({})


def test_the_command_is_available_to_the_secretary_not_only_admin():
    """The CEO asks this in the secretary chat, which serves the personal domain."""
    from my_crew.agent.ops_catalog import catalog_for_domain

    assert "list_lessons" in catalog_for_domain("personal")
    assert "list_lessons" in catalog_for_domain("admin")
    assert catalog_for_domain("personal")["list_lessons"]["readonly"] is True
