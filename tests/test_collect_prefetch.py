"""v75 phase 3: hybrid collect launcher — query derivation, fail-open, routing."""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.runtime.collect_prefetch import derive_queries, prefetch_for_step


def _step(title):
    return SimpleNamespace(title=title)


def test_derive_queries_plain_title_is_one_query():
    assert derive_queries(_step("Khảo sát thị trường xe điện Việt Nam")) == [
        "Khảo sát thị trường xe điện Việt Nam"
    ]


def test_derive_queries_entity_list_adds_topic_prefixed_variants():
    qs = derive_queries(_step("Thu thập giá Google One, iCloud+, Dropbox"))
    assert qs[0] == "Thu thập giá Google One, iCloud+, Dropbox"
    assert len(qs) == 3
    assert any("iCloud+" in q and "Thu thập giá" in q for q in qs[1:])
    assert any("Dropbox" in q for q in qs[1:])


def test_derive_queries_caps_at_three():
    qs = derive_queries(_step("Khảo sát A1, B2, C3, D4, E5"))
    assert len(qs) == 3


def _settings(tmp_path):
    return SimpleNamespace(tavily_api_key="t", brave_api_key=None,
                           data_dir=str(tmp_path / "agent"))


def _loaded():
    return SimpleNamespace(web_search=True)


def test_prefetch_returns_bundle_when_any_query_hits(tmp_path, monkeypatch):
    from my_crew.tools.search_result_formatter import SearchResult

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    hit = SearchResult(title="Giá Google One", snippet="2TB $9.99", source="one.google.com")
    outcomes = iter([([hit], "ok"), ([], "empty"), ([], "provider_error")])
    monkeypatch.setattr("my_crew.tools.web_search_tool.web_search_outcome",
                        lambda q, **kw: next(outcomes))
    bundle = prefetch_for_step(_loaded(), _settings(tmp_path),
                               _step("Thu thập giá Google One, iCloud+, Dropbox"))
    assert "KẾT QUẢ TÌM KIẾM" in bundle
    assert "[KHÔNG CÓ KẾT QUẢ]" in bundle  # per-query sentinel preserved
    assert "[LỖI NGUỒN TÌM KIẾM]" in bundle


def test_prefetch_fails_open_when_no_query_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    monkeypatch.setattr("my_crew.tools.web_search_tool.web_search_outcome",
                        lambda q, **kw: ([], "provider_error"))
    assert prefetch_for_step(_loaded(), _settings(tmp_path), _step("Khảo sát X")) == ""


def test_keep_sentinels_reports_a_total_blackout_instead_of_failing_open(
    tmp_path, monkeypatch,
):
    """A sprint step has no tool loop to fall back to, so "" would read as "we never
    searched" and turn a provider outage into "đã tìm nhưng không có dữ liệu"."""
    from my_crew.runtime.collect_prefetch import prefetch_queries

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    monkeypatch.setattr("my_crew.tools.web_search_tool.web_search_outcome",
                        lambda q, **kw: ([], "provider_error"))
    bundle = prefetch_queries(_loaded(), _settings(tmp_path), ["giá Netflix"],
                              keep_sentinels=True)
    assert "[LỖI NGUỒN TÌM KIẾM]" in bundle
    assert "giá Netflix" in bundle


def test_a_hard_failure_mid_loop_keeps_what_was_already_collected(tmp_path, monkeypatch):
    """The exception path used to `return ""` from inside the loop, throwing away the
    blocks already gathered. For a `keep_sentinels` caller that turns a partial outage
    into a total one — and the queries it never ran get reported as "đã tìm nhưng
    không đủ kết quả", which is the exact confusion the sentinels exist to prevent."""
    from my_crew.runtime.collect_prefetch import prefetch_queries
    from my_crew.tools.search_result_formatter import SearchResult

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    hit = SearchResult(title="Giá Netflix", snippet="180k/tháng", source="netflix.com")

    def _outcome(query, **_kw):
        if "Netflix" in query:
            return ([hit], "ok")
        raise RuntimeError("provider socket died")

    monkeypatch.setattr("my_crew.tools.web_search_tool.web_search_outcome", _outcome)
    bundle = prefetch_queries(
        _loaded(), _settings(tmp_path), ["giá Netflix", "giá Spotify"], keep_sentinels=True,
    )
    assert "KẾT QUẢ TÌM KIẾM" in bundle and "180k/tháng" in bundle
    assert "[LỖI NGUỒN TÌM KIẾM]" in bundle and "giá Spotify" in bundle


def test_a_hard_failure_still_fails_open_for_the_tool_loop_caller(tmp_path, monkeypatch):
    """Without `keep_sentinels` the caller has its own tool loop, which will search
    again — half a bundle is noise to it, so "" stays the right answer."""
    from my_crew.runtime.collect_prefetch import prefetch_queries

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

    def _boom(query, **_kw):
        raise RuntimeError("provider socket died")

    monkeypatch.setattr("my_crew.tools.web_search_tool.web_search_outcome", _boom)
    assert prefetch_queries(_loaded(), _settings(tmp_path), ["giá Netflix"]) == ""


def test_never_searched_is_reported_apart_from_searched_and_found_nothing(tmp_path):
    """A missing opt-in or a missing provider key means no query ran at all. Returning
    "" to a caller with no fallback let it draft from model memory while its own note
    claimed a search had happened."""
    from my_crew.runtime.collect_prefetch import NO_SEARCH_CAPABILITY, prefetch_queries

    no_flag = SimpleNamespace(web_search=False)
    out = prefetch_queries(no_flag, _settings(tmp_path), ["giá X"], keep_sentinels=True)
    assert NO_SEARCH_CAPABILITY in out and "web_search" in out

    no_keys = SimpleNamespace(tavily_api_key=None, brave_api_key=None, data_dir=str(tmp_path))
    out = prefetch_queries(_loaded(), no_keys, ["giá X"], keep_sentinels=True)
    assert NO_SEARCH_CAPABILITY in out
    # Not a per-query sentinel: no query was ever issued, so none may be quoted.
    assert "truy vấn" not in out


def test_prefetch_skips_without_optin_or_keys(tmp_path):
    no_flag = SimpleNamespace(web_search=False)
    assert prefetch_for_step(no_flag, _settings(tmp_path), _step("X")) == ""
    no_keys = SimpleNamespace(tavily_api_key=None, brave_api_key=None,
                              data_dir=str(tmp_path))
    assert prefetch_for_step(_loaded(), no_keys, _step("X")) == ""


def test_routing_prefetched_web_step_runs_native(monkeypatch):
    from my_crew.runtime_backends.protocol import resolve_step_runtime

    class _Cfg:
        kind = "create_agent"

    loaded = SimpleNamespace(agent_runtime=_Cfg(), profile_id="a")
    step = SimpleNamespace(needs_shell=False, needs_web=True, step_type="work",
                           intervention_count=0)
    assert type(resolve_step_runtime(loaded, step)).__name__ == "ToolCallingRuntime"
    assert type(resolve_step_runtime(loaded, step, prefetched=True)).__name__ == (
        "NativeGraphRuntime"
    )


def test_loop_tier_web_search_tool_mirrors_the_3_path_sentinels(tmp_path, monkeypatch):
    """The tool-loop's web.search must distinguish outage from clean-empty exactly
    like the native hook — the Zetakron e2e ran on the loop tier and the old text
    could not say WHY nothing came back."""
    from my_crew.runtime_backends.read_only_toolset import _web_search_tool

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    settings = SimpleNamespace(tavily_api_key="t", brave_api_key=None,
                               data_dir=str(tmp_path / "agent"))
    outcomes = {"v": ([], "provider_error")}
    monkeypatch.setattr("my_crew.tools.web_search_tool.web_search_outcome",
                        lambda q, **kw: outcomes["v"])
    tool = _web_search_tool(settings)
    assert tool is not None
    assert "LỖI NGUỒN" in tool({"query": "giá X"})
    outcomes["v"] = ([], "empty")
    assert "KHÔNG CÓ KẾT QUẢ" in tool({"query": "giá X"})
