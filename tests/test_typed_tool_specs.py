"""Typed tool specs (thin-loop tier): dsh-convention names/schemas over the legacy toolset.

The specs are the wire contract the model was RL-trained against (snake_case names,
typed params) — the legacy `(args: dict)` callables stay untouched underneath.
"""

from __future__ import annotations

from my_crew.runtime_backends.typed_tool_specs import ToolSpec, build_typed_specs


def _map(*names: str) -> dict:
    return {n: (lambda args: "ok") for n in names}


def test_known_tools_map_to_snake_case_specs():
    specs = build_typed_specs(_map("web.search", "web.scrape", "history.search"))
    by_name = {s.name: s for s in specs}
    assert set(by_name) == {"web_search", "web_fetch", "history_search"}
    assert by_name["web_search"].legacy_name == "web.search"
    assert by_name["web_fetch"].legacy_name == "web.scrape"
    assert by_name["history_search"].legacy_name == "history.search"


def test_only_tools_present_in_map_are_offered():
    specs = build_typed_specs(_map("web.search"))
    assert [s.name for s in specs] == ["web_search"]


def test_schemas_declare_required_params():
    specs = {s.name: s for s in build_typed_specs(
        _map("web.search", "web.scrape", "confluence.page", "history.search", "jira.issues")
    )}
    assert specs["web_search"].parameters["required"] == ["query"]
    assert specs["web_fetch"].parameters["required"] == ["url"]
    assert specs["confluence_page"].parameters["required"] == ["page_id"]
    # history_search: query required, days/agent optional
    hs = specs["history_search"].parameters
    assert hs["required"] == ["query"]
    assert hs["properties"]["days"]["type"] == "integer"
    assert hs["properties"]["agent"]["type"] == "string"
    # zero-param tools still carry a valid (empty) object schema
    ji = specs["jira_issues"].parameters
    assert ji["type"] == "object" and ji["properties"] == {}


def test_every_spec_has_description_and_object_schema():
    all_legacy = [
        "jira.issues", "github.prs", "linear.issues", "confluence.page", "web.scrape",
        "web.search", "academic.search", "gws.gmail", "gws.calendar", "gws.drive",
        "history.search",
    ]
    specs = build_typed_specs(_map(*all_legacy))
    assert len(specs) == len(all_legacy)
    for s in specs:
        assert s.description.strip(), s.name
        assert s.parameters["type"] == "object", s.name
        assert "_" in s.name or s.name.isalpha(), s.name
        assert "." not in s.name, s.name


def test_web_fetch_repair_maps_query_to_url():
    specs = {s.name: s for s in build_typed_specs(_map("web.scrape"))}
    fix = specs["web_fetch"].prepare_arguments
    assert fix is not None
    assert fix({"query": "https://x.example"}) == {"url": "https://x.example"}
    # a real url arg passes through untouched, stray whitespace trimmed
    assert fix({"url": "  https://y.example "}) == {"url": "https://y.example"}
    # url wins when both present
    assert fix({"url": "https://a", "query": "b"}) == {"url": "https://a"}


def test_unregistered_tool_gets_generic_query_fallback():
    # forward-compat: a runtime tool with no registered spec keeps the OLD loop's
    # one-string-query shape instead of silently disappearing from the model's menu
    specs = build_typed_specs(_map("future.thing"))
    assert len(specs) == 1
    s = specs[0]
    assert s.name == "future_thing"
    assert s.legacy_name == "future.thing"
    assert s.parameters["properties"].keys() == {"query"}


def test_openai_wire_shape():
    (spec,) = build_typed_specs(_map("web.search"))
    wire = spec.as_openai_tool()
    assert wire["type"] == "function"
    assert wire["function"]["name"] == "web_search"
    assert wire["function"]["parameters"] is spec.parameters


def test_specs_are_frozen():
    (spec,) = build_typed_specs(_map("web.search"))
    assert isinstance(spec, ToolSpec)
    try:
        spec.name = "x"  # type: ignore[misc]
        raise AssertionError("ToolSpec must be frozen")
    except AttributeError:
        pass
