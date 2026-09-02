"""`ops_assign_team_task._escalation_routable` + its wiring into `preview_assign_team_task`
(v12 MAJOR-6): a team task must never be draftable if its coordinator's Telegram
escalation path is unroutable — the ticker's `escalate` collaborator would silently
fail (see `team_tick_collaborators.make_escalate`) and the task would have no safety
net at all for a stuck/failed step.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.ops_assign_team_task as mod
import my_crew.profile.loader as loader_mod
import my_crew.runtime.company as company_mod
import my_crew.runtime.registry as registry_mod
from my_crew.runtime.registry import RegistryEntry


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Every test in this module writes through the shared cross-agent root (store,
    artifacts, office-room appends) — pin it to tmp_path so no test can touch the
    real install's .data (the office room is a real user-visible surface)."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

def _company(coordinator_id):
    return SimpleNamespace(name="", coordinator_id=coordinator_id, team_task_cap_usd=2.0)


def _profile_with_telegram(*, ops_operator_id: str, chat_ids: tuple[str, ...], domain: str = "pm"):
    telegram = SimpleNamespace(
        bot_token_env="X", chat_ids=chat_ids, poll_minutes=5, ops_operator_id=ops_operator_id
    )
    return SimpleNamespace(domain=domain, config=SimpleNamespace(telegram=telegram))


def _profile_no_telegram(*, domain: str = "pm"):
    return SimpleNamespace(domain=domain, config=SimpleNamespace(telegram=None))


# --- _escalation_routable -----------------------------------------------------------


def test_escalation_routable_true_when_operator_in_chat_ids(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        loader_mod, "load_profile",
        lambda agent_id, **kw: _profile_with_telegram(
            ops_operator_id="op-1", chat_ids=("op-1", "group-2")
        ),
    )
    assert mod._escalation_routable() is True


def test_escalation_routable_false_when_no_coordinator_configured(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company(None))
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_coordinator_profile_unloadable(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))

    def _raise(agent_id, **kw):
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _raise)
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_no_telegram_configured(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(loader_mod, "load_profile", lambda agent_id, **kw: _profile_no_telegram())
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_no_operator_id_set(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        loader_mod, "load_profile",
        lambda agent_id, **kw: _profile_with_telegram(ops_operator_id="", chat_ids=("g1",)),
    )
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_operator_not_in_chat_ids(monkeypatch):
    """The real bug this finding targets: an operator id is set but NOT allowlisted —
    `telegram_write.send_telegram_message` would refuse every escalation send."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        loader_mod, "load_profile",
        lambda agent_id, **kw: _profile_with_telegram(
            ops_operator_id="op-1", chat_ids=("some-other-chat",)
        ),
    )
    assert mod._escalation_routable() is False


def test_escalation_routable_true_via_admin_mirror_when_coordinator_has_no_binding_of_its_own(
    monkeypatch,
):
    """The mirror path (v12 final-review escalation-reachability redesign): the
    coordinator itself has no Telegram binding, but an ENABLED admin-domain agent does
    — every escalation reaches it via the office-room `milestone` mirror
    (`milestone_mirror_runner`), so the task is still routable."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="admin", enabled=True),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "admin":
            return _profile_with_telegram(
                ops_operator_id="op-1", chat_ids=("op-1",), domain="admin",
            )
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is True


def test_escalation_routable_false_when_neither_coordinator_nor_any_admin_agent_has_a_route(
    monkeypatch,
):
    """Neither the fast path (coordinator's own binding) nor the mirror path (an
    enabled admin-domain agent's binding) works — genuinely unroutable."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="admin", enabled=True),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "admin":
            return _profile_no_telegram(domain="admin")
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is False


def test_escalation_routable_ignores_a_disabled_admin_agents_route(monkeypatch):
    """A disabled admin agent's binding does not count — `milestone_mirror_runner`
    only runs for an ENABLED admin agent's scheduled ops-tick."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="admin", enabled=False),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "admin":
            return _profile_with_telegram(
                ops_operator_id="op-1", chat_ids=("op-1",), domain="admin",
            )
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is False


def test_escalation_routable_ignores_a_non_admin_agents_route(monkeypatch):
    """An enabled agent with a working Telegram binding but domain != "admin" does not
    provide the mirror path — `milestone_mirror_runner`'s ops-tick is scheduled only
    for admin-domain agents (`my_crew.runtime.service._effective_schedule`)."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="sales", enabled=True),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "sales":
            return _profile_with_telegram(
                ops_operator_id="op-1", chat_ids=("op-1",), domain="pm",
            )
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is False


# --- preview_assign_team_task wiring -------------------------------------------------


def test_preview_assign_team_task_blocks_with_vietnamese_error_when_unroutable(monkeypatch):
    monkeypatch.setattr(mod, "_escalation_routable", lambda: False)
    with pytest.raises(ValueError, match="chưa giao việc được"):
        mod.preview_assign_team_task({"brief": "chuẩn bị demo"})


def test_unroutable_error_names_the_screen_that_fixes_it(monkeypatch):
    """This block is the first wall a brand-new install hits, so the message has to
    lead somewhere. Naming the tab keeps it from being a dead end the way the old
    wording was, which only described `ops_operator_id` and `chat_ids`."""
    monkeypatch.setattr(mod, "_escalation_routable", lambda: False)
    with pytest.raises(ValueError) as excinfo:
        mod.preview_assign_team_task({"brief": "chuẩn bị demo"})
    assert "Kênh" in str(excinfo.value)


def test_preview_assign_team_task_proceeds_past_escalation_gate_when_routable(monkeypatch):
    """Escalation check passes -> the function proceeds to the NEXT gate (staff
    roster), proving the escalation check does not block a routable setup. We stop the
    test right after that by making the staff roster empty (a distinct, well-understood
    failure) rather than standing up the full LLM/store stack."""
    monkeypatch.setattr(mod, "_escalation_routable", lambda: True)
    monkeypatch.setattr(mod, "_staff_roster", lambda: [])
    with pytest.raises(ValueError, match="chưa có nhân sự"):
        mod.preview_assign_team_task({"brief": "chuẩn bị demo"})


# --- v63 autopilot: auto-confirm + per-task opt-out ----------------------------------


def _fake_decomposed_task():
    from my_crew.agent.task_decomposition import DecomposedTask, TeamStepPlan

    return DecomposedTask(steps=(
        TeamStepPlan(step_id="s1", title="soạn nội dung", assigned_to="agent-a"),
    ))


def _wire_full_preview(monkeypatch):
    monkeypatch.setattr(mod, "_escalation_routable", lambda: True)
    monkeypatch.setattr(mod, "_staff_roster", lambda: [("agent-a", "office")])
    monkeypatch.setattr(
        mod, "_decompose_with_retries",
        lambda brief, staff, pic: (_fake_decomposed_task(), None),
    )


def _autopilot_company(monkeypatch):
    company = SimpleNamespace(
        name="", coordinator_id="coord-1", team_task_cap_usd=2.0,
        team_task_auto_confirm=False, autopilot=True,
    )
    monkeypatch.setattr(company_mod, "load_company", lambda path=None: company)


def _store():
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    return TeamTaskStore(team_tasks_db_path())


def test_autopilot_auto_confirms_the_previewed_plan(monkeypatch):
    _wire_full_preview(monkeypatch)
    _autopilot_company(monkeypatch)

    slots = {"brief": "soạn nội dung tuần"}
    reply = mod.preview_assign_team_task(slots)

    assert "ĐÃ TỰ XÁC NHẬN" in reply
    assert slots.get("auto_confirmed") == "1"
    store = _store()
    try:
        task = store.get(slots["task_id"])
        assert task.status == "open"  # confirmed through the SAME hash-bind path
        assert task.require_ceo_approval is False
    finally:
        store.close()


def test_opt_out_phrase_pins_the_task_to_manual_gates(monkeypatch):
    _wire_full_preview(monkeypatch)
    _autopilot_company(monkeypatch)

    slots = {"brief": "soạn nội dung tuần, vụ này để anh duyệt"}
    reply = mod.preview_assign_team_task(slots)

    assert "Xác nhận giao việc" in reply  # manual confirm question, not auto-run
    assert "auto_confirmed" not in slots
    store = _store()
    try:
        task = store.get(slots["task_id"])
        assert task.status == "planning"  # draft awaiting the CEO's confirm
        assert task.require_ceo_approval is True  # persisted for the task's whole life
    finally:
        store.close()


def test_widen_terminal_deps_gives_the_sink_every_other_step():
    """A step reads ONLY its direct deps' artifacts — data does not flow transitively.
    Models keep emitting linear chains (finalize deps=[qa]) that blind the synthesis
    step to the research it must cite, so the fan-in is enforced in code post-validate."""
    from my_crew.agent.ops_assign_team_task import _widen_terminal_deps
    from my_crew.agent.task_decomposition import DecomposedTask, TeamStepPlan

    linear = DecomposedTask(pic_id="a", steps=(
        TeamStepPlan(step_id="research", title="t", assigned_to="a"),
        TeamStepPlan(step_id="draft", title="t", assigned_to="b", deps=("research",)),
        TeamStepPlan(step_id="qa", title="t", assigned_to="c", deps=("draft",)),
        TeamStepPlan(step_id="finalize", title="t", assigned_to="a", deps=("qa",)),
    ))
    widened = _widen_terminal_deps(linear)
    fin = next(s for s in widened.steps if s.step_id == "finalize")
    assert set(fin.deps) == {"research", "draft", "qa"}
    # Non-terminal steps untouched; single-step plans pass through unchanged.
    assert next(s for s in widened.steps if s.step_id == "draft").deps == ("research",)
    one = DecomposedTask(steps=(TeamStepPlan(step_id="s", title="t", assigned_to="a"),))
    assert _widen_terminal_deps(one) is one


def test_decompose_falls_back_to_code_side_fanout_when_the_model_never_splits(
    monkeypatch,
):
    """Benchmark B live shape: a 5-entity brief where the model returns the SAME
    packed plan through every retry. The old fail-open accepted it (one react-loop
    over 5 entities → truncated output, ~17min for that step); now the last attempt
    splits the packed collect step in code and the assign returns a fanned DAG."""
    import json

    packed_plan = json.dumps({
        "pic_id": "agent-a",
        "steps": [
            {"step_id": "research", "title": "Tra cứu cả 5 công cụ",
             "assigned_to": "agent-a", "deps": [], "needs_web": True,
             "acceptance": "kèm link nguồn"},
            {"step_id": "finalize", "title": "Tổng hợp báo cáo",
             "assigned_to": "agent-a", "deps": ["research"],
             "acceptance": "bản nộp có bảng so sánh"},
        ],
    })
    calls = []

    class _Llm:
        def complete(self, messages, **_kw):
            calls.append(messages)
            return SimpleNamespace(content=packed_plan, cost_usd=0.001)

    monkeypatch.setattr(mod, "_build_llm", lambda: (_Llm(), None))

    brief = ("So sánh 5 công cụ note-taking: Notion, Obsidian, Evernote, Apple Notes, "
             "Google Keep. Nêu rõ nguồn.")
    task, cost = mod._decompose_with_retries(brief, [("agent-a", "office")])

    # The model got every retry (the bias stays a bias) before code took over.
    assert len(calls) == mod._MAX_DECOMPOSE_ATTEMPTS
    subs = [s for s in task.steps if s.needs_web and not s.deps]
    assert len(subs) == 2
    assert all("research" != s.step_id for s in task.steps)
    for entity in ("Notion", "Obsidian", "Evernote", "Apple Notes", "Google Keep"):
        assert sum(entity in s.title for s in subs) == 1, entity
    # `_widen_terminal_deps` ran on the SPLIT plan: the terminal fans in on the subs.
    fin = next(s for s in task.steps if s.step_id == "finalize")
    assert set(fin.deps) == {s.step_id for s in subs}
    assert cost == pytest.approx(0.001 * mod._MAX_DECOMPOSE_ATTEMPTS)


def test_decompose_repairs_a_terminal_step_handed_to_the_wrong_agent(monkeypatch):
    """Live UAT shape: the prompt states the PIC-terminal rule and the model still
    assigns the final synthesis elsewhere. Reassigning is a code-side fix, so the
    assign must succeed on the FIRST completion instead of burning re-prompts."""
    import json

    plan = json.dumps({
        "pic_id": "agent-a",
        "steps": [
            {"step_id": "research", "title": "Tra cứu", "assigned_to": "agent-b",
             "deps": [], "acceptance": "kèm link nguồn"},
            {"step_id": "finalize", "title": "Tổng hợp báo cáo",
             "assigned_to": "agent-b", "deps": ["research"],
             "acceptance": "bản nộp có bảng so sánh"},
        ],
    })
    calls = []

    class _Llm:
        def complete(self, messages, **_kw):
            calls.append(messages)
            return SimpleNamespace(content=plan, cost_usd=0.001)

    monkeypatch.setattr(mod, "_build_llm", lambda: (_Llm(), None))

    task, cost = mod._decompose_with_retries(
        "Tóm tắt chi phí", [("agent-a", "office"), ("agent-b", "office")])

    assert len(calls) == 1  # no retry burned on a violation code can fix
    assert cost == pytest.approx(0.001)
    fin = next(s for s in task.steps if s.step_id == "finalize")
    assert fin.assigned_to == "agent-a"  # handed back to the PIC
    # everything else the model decided stays exactly as it was
    assert next(s for s in task.steps if s.step_id == "research").assigned_to == "agent-b"


def test_decompose_repair_honours_the_ceo_named_pic_over_the_model(monkeypatch):
    import json

    plan = json.dumps({
        "pic_id": "agent-b",  # the model's own pick loses to the CEO's @-name
        "steps": [
            {"step_id": "research", "title": "Tra cứu", "assigned_to": "agent-b",
             "deps": [], "acceptance": "kèm link nguồn"},
            {"step_id": "finalize", "title": "Tổng hợp", "assigned_to": "agent-b",
             "deps": ["research"], "acceptance": "bản nộp có bảng so sánh"},
        ],
    })

    class _Llm:
        def complete(self, messages, **_kw):
            return SimpleNamespace(content=plan, cost_usd=0.001)

    monkeypatch.setattr(mod, "_build_llm", lambda: (_Llm(), None))

    task, _cost = mod._decompose_with_retries(
        "Tóm tắt chi phí", [("agent-a", "office"), ("agent-b", "office")],
        pic_requested="agent-a")

    assert next(s for s in task.steps if s.step_id == "finalize").assigned_to == "agent-a"


def test_decompose_leaves_an_ambiguous_multi_terminal_plan_to_the_model(monkeypatch):
    """Which of several terminals is 'the' final step is a judgement about the work,
    not a mechanical fix — that violation still goes back through the retry loop."""
    import json

    plan = json.dumps({
        "pic_id": "agent-a",
        "steps": [
            {"step_id": "one", "title": "Nhánh 1", "assigned_to": "agent-b", "deps": [],
             "acceptance": "kèm link nguồn"},
            {"step_id": "two", "title": "Nhánh 2", "assigned_to": "agent-b", "deps": [],
             "acceptance": "kèm link nguồn"},
        ],
    })
    calls = []

    class _Llm:
        def complete(self, messages, **_kw):
            calls.append(messages)
            return SimpleNamespace(content=plan, cost_usd=0.001)

    monkeypatch.setattr(mod, "_build_llm", lambda: (_Llm(), None))

    with pytest.raises(mod.DecompositionError):
        mod._decompose_with_retries(
            "Tóm tắt chi phí", [("agent-a", "office"), ("agent-b", "office")])
    assert len(calls) == mod._MAX_DECOMPOSE_ATTEMPTS


def test_decompose_sends_an_unmeasurable_step_back_then_refuses_the_plan(monkeypatch):
    """A step whose acceptance nobody could grade gets the retry loop (the model is told
    WHICH step and WHY); a model that never fixes it makes the plan not crew-shaped, and
    that verdict must survive the loop as its own error so the router can fall back to
    a sprint — a generic "không phân rã được" would end the assign instead."""
    import json

    from my_crew.agent.task_decomposition import UnmeasurablePlanError

    # Two parallel branches into a merge: nothing here is a fold candidate, so the
    # unmeasurable branch cannot disappear into a neighbour's measurable acceptance.
    plan = json.dumps({
        "pic_id": "agent-a",
        "steps": [
            {"step_id": "research", "title": "Tra cứu giá", "assigned_to": "agent-a",
             "deps": [], "acceptance": "đầy đủ và chính xác"},
            {"step_id": "research_2", "title": "Tra cứu nguồn cung", "assigned_to": "agent-a",
             "deps": [], "acceptance": "kèm link nguồn"},
            {"step_id": "finalize", "title": "Tổng hợp", "assigned_to": "agent-a",
             "deps": ["research", "research_2"], "acceptance": "bản nộp có bảng so sánh"},
        ],
    })
    calls = []

    class _Llm:
        def complete(self, messages, **_kw):
            calls.append(messages)
            return SimpleNamespace(content=plan, cost_usd=0.001)

    monkeypatch.setattr(mod, "_build_llm", lambda: (_Llm(), None))

    with pytest.raises(UnmeasurablePlanError) as info:
        mod._decompose_with_retries("soạn báo cáo ngắn về giá thuê", [("agent-a", "office")])

    assert len(calls) == mod._MAX_DECOMPOSE_ATTEMPTS
    retry_prompt = str(calls[1])
    assert "'research'" in retry_prompt and "không đo được" in retry_prompt
    # The spend is not lost: the sprint fallback accounts for it.
    assert info.value.cost_usd == pytest.approx(0.001 * mod._MAX_DECOMPOSE_ATTEMPTS)


def test_a_mail_step_is_persisted_with_its_flag_so_the_confirmed_hash_still_verifies(
    monkeypatch,
):
    """`decomposition_content_hash` binds `needs_mail` into the confirm-time hash, and
    the ticker recomputes that hash over the persisted rows before every dispatch. A row
    written WITHOUT the flag therefore fails that recheck and the task stalls on
    `plan_hash mismatch` before its first step runs — measured live on a mail brief:
    "Rà soát hộp thư..." → both steps pending forever, nothing ever spawned."""
    from my_crew.agent.task_decomposition import (
        DecomposedTask,
        TeamStepPlan,
        decomposition_content_hash,
    )

    plan = DecomposedTask(steps=(
        TeamStepPlan(step_id="read_mail", title="đọc hộp thư", assigned_to="agent-a",
                     needs_mail=True),
        TeamStepPlan(step_id="summarize", title="tổng hợp", assigned_to="agent-a",
                     deps=("read_mail",)),
    ))
    _wire_full_preview(monkeypatch)
    monkeypatch.setattr(mod, "_decompose_with_retries", lambda brief, staff, pic: (plan, None))
    _autopilot_company(monkeypatch)

    slots = {"brief": "đọc hộp thư rồi tổng hợp đơn hàng tuần"}
    mod.preview_assign_team_task(slots)

    store = _store()
    try:
        task = store.get(slots["task_id"])
    finally:
        store.close()
    by_id = {s.step_id: s for s in task.steps}
    assert by_id["read_mail"].needs_mail is True
    assert by_id["summarize"].needs_mail is False
    # The exact check the ticker runs on every tick — over the rows, not the plan.
    assert decomposition_content_hash(task) == task.plan_hash == slots["plan_hash"]
