"""v43 Phase 3: TaskCapMiddleware hard-caps `task` delegations.

The (N+1)-th `task` call is refused in CODE (error ToolMessage, inner handler NOT invoked) so a
deep_agent cannot spawn unbounded subagents and blow past the container lease. Non-`task` tools are
never counted or blocked. Counter is per-instance → per-run (a fresh middleware per
run_deep_agent_work call).
"""

from __future__ import annotations

from src.runtime_backends.deep_team_task_cap import TaskCapMiddleware


class _Req:
    def __init__(self, name, cid="c"):
        self.tool_call = {"name": name, "args": {}, "id": cid}


def _handler_factory():
    calls = []

    def handler(req):
        from langchain_core.messages import ToolMessage

        calls.append(req.tool_call["name"])
        return ToolMessage(content="ok", tool_call_id=req.tool_call["id"])

    return handler, calls


def test_task_calls_pass_up_to_cap():
    m = TaskCapMiddleware(max_calls=3)
    handler, calls = _handler_factory()
    for _ in range(3):
        r = m.wrap_tool_call(_Req("task"), handler)
        assert r.content == "ok"
    assert calls == ["task", "task", "task"]


def test_task_call_over_cap_is_refused_without_invoking_handler():
    m = TaskCapMiddleware(max_calls=2)
    handler, calls = _handler_factory()
    m.wrap_tool_call(_Req("task"), handler)
    m.wrap_tool_call(_Req("task"), handler)
    refused = m.wrap_tool_call(_Req("task", "c3"), handler)
    assert refused.status == "error"
    assert "giới hạn" in refused.content
    assert refused.tool_call_id == "c3"
    assert calls == ["task", "task"]  # 3rd never reached the handler


def test_non_task_tool_never_counted_or_blocked():
    m = TaskCapMiddleware(max_calls=1)
    handler, calls = _handler_factory()
    # many non-task calls do not consume the budget
    for name in ("write_file", "read_file", "execute", "grep"):
        r = m.wrap_tool_call(_Req(name), handler)
        assert r.content == "ok"
    # the single task budget is still available
    r = m.wrap_tool_call(_Req("task"), handler)
    assert r.content == "ok"
    # now the next task is refused
    assert m.wrap_tool_call(_Req("task"), handler).status == "error"
    assert calls == ["write_file", "read_file", "execute", "grep", "task"]


def test_counter_is_per_instance():
    handler, _calls = _handler_factory()
    m1 = TaskCapMiddleware(max_calls=1)
    m1.wrap_tool_call(_Req("task"), handler)
    assert m1.wrap_tool_call(_Req("task"), handler).status == "error"
    # a fresh instance (new run) gets a fresh budget
    m2 = TaskCapMiddleware(max_calls=1)
    assert m2.wrap_tool_call(_Req("task"), handler).content == "ok"


def test_cap_holds_under_parallel_tool_calls():
    """ToolNode runs parallel `task` calls from one turn on a thread pool. The lock must ensure at
    most max_calls handler invocations even when many threads race the counter."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    max_calls = 3
    n_threads = 24
    m = TaskCapMiddleware(max_calls=max_calls)

    lock = threading.Lock()
    passed = []

    def handler(req):
        from langchain_core.messages import ToolMessage

        # small work under the run-simulated section; record a pass
        with lock:
            passed.append(req.tool_call["id"])
        return ToolMessage(content="ok", tool_call_id=req.tool_call["id"])

    def one(i):
        r = m.wrap_tool_call(_Req("task", f"c{i}"), handler)
        return getattr(r, "status", None)

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        statuses = list(ex.map(one, range(n_threads)))

    # exactly max_calls got through to the handler; the rest were refused.
    assert len(passed) == max_calls
    assert statuses.count("error") == n_threads - max_calls
