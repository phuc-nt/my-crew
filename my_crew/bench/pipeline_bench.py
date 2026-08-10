"""Measure the sprint pipeline's decisions without a network or a daemon.

The live benchmark answers "was it faster that day". This one answers the question
that actually protects the architecture: **how many searches and model calls does the
CODE decide to make for a given brief?** That count is what v77 fixed in place, and it
is what a careless prompt or regex edit would silently inflate — a brief that used to
cost 3 model calls quietly costing 5 is the whole 780s failure mode coming back.

The model is scripted and search is a stub, so a run is deterministic and takes
milliseconds. Wall-clock here is meaningless by construction and is not reported.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

from my_crew.runtime.sprint_runner import build_sprint_work, entity_queries, resolve_entities


@dataclass(frozen=True)
class BriefCase:
    """One benchmark brief plus what a healthy pipeline should spend on it."""

    name: str
    goal: str
    acceptance: str = ""
    #: Entities the router should find. Empty means "no enumeration in this brief".
    expected_entities: tuple[str, ...] = ()
    #: Upper bound on model calls. The pipeline is draft + up to MAX_REVISE_ROUNDS.
    max_llm_calls: int = 3
    #: Upper bound on searches, enforced by MAX_SPRINT_PREFETCH_QUERIES + revise.
    max_searches: int = 8


@dataclass
class PipelineResult:
    """What one scripted run of the pipeline actually spent."""

    case: str
    llm_calls: int
    searches: int
    queries: list[str] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    output_chars: int = 0

    def violations(self, case: BriefCase) -> list[str]:
        """Budget breaches, worded so a failing report says what to go look at."""
        out: list[str] = []
        if self.llm_calls > case.max_llm_calls:
            out.append(f"{self.llm_calls} model calls > budget {case.max_llm_calls}")
        if self.searches > case.max_searches:
            out.append(f"{self.searches} searches > budget {case.max_searches}")
        if case.expected_entities and tuple(self.entities) != case.expected_entities:
            out.append(f"entities {self.entities} != expected {list(case.expected_entities)}")
        return out


class _ScriptedLlm:
    """Replays fixed replies and counts calls. No network, no variance."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages):  # noqa: ANN001 — mirrors LlmClient.complete
        self.calls.append(list(messages))
        reply = self._replies.pop(0) if self._replies else ""
        return SimpleNamespace(content=reply, cost_usd=0.0, prompt_tokens=0, completion_tokens=0)


def run_case(
    case: BriefCase,
    *,
    draft: str,
    revisions: list[str] | None = None,
    search_result: Callable[[str], str] | None = None,
    monkeypatch=None,  # noqa: ANN001 — pytest's fixture, passed through by callers
) -> PipelineResult:
    """Run one brief through the real pipeline with a scripted model.

    `draft` is what the model "writes" first; `revisions` are its answers to any
    revise rounds the coverage check triggers. A caller that wants to prove the
    pipeline STOPS supplies a draft that never covers everything and checks the run
    still terminates within budget.
    """
    import my_crew.llm.client as client_mod
    import my_crew.runtime.sprint_runner as runner_mod

    llm = _ScriptedLlm([draft, *(revisions or [])])
    if monkeypatch is None:
        raise ValueError("run_case needs pytest's monkeypatch to install the scripted model")
    monkeypatch.setattr(runner_mod, "LlmClient", lambda _s: llm, raising=False)
    monkeypatch.setattr(client_mod, "LlmClient", lambda _s: llm)

    seen_queries: list[str] = []
    phases: list[str] = []

    def _prefetch(_loaded, _settings, queries: list[str]) -> str:
        seen_queries.extend(queries)
        render = search_result or (lambda q: f"KẾT QUẢ cho {q}: nội dung mẫu.")
        return "\n".join(f"[{q}]\n{render(q)}" for q in queries)

    work = build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        acceptance=case.acceptance,
        prefetch=_prefetch,
        on_phase=phases.append,
    )
    text, _cost = work(case.goal, "", None)

    return PipelineResult(
        case=case.name,
        llm_calls=len(llm.calls),
        searches=len(seen_queries),
        queries=list(seen_queries),
        phases=list(phases),
        entities=resolve_entities(case.goal, case.acceptance),
        output_chars=len(text or ""),
    )


def planned_queries(case: BriefCase) -> list[str]:
    """What the router WOULD search for, without running the pipeline.

    Cheap enough to assert on every brief in the suite, and it is the single decision
    that broke twice during v77 UAT: a topic phrase severed from its head noun
    searches for nothing in particular.
    """
    return entity_queries(case.goal, case.acceptance)
