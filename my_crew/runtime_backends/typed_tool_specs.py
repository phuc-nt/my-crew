"""Typed tool specs for the thin tool loop — dsh-convention names over the legacy toolset.

Why this layer exists: frontier tool-calling models are RL-trained against lowercase
snake_case tool names with TYPED parameters (`web_search(query)`, `web_fetch(url)`), not
against dotted names taking one free-form string. The legacy `build_read_toolset` map
(`web.search` → callable(args: dict)) stays the execution layer; this module only declares
the wire-facing schema and the name mapping, so the moat (positive read allowlist,
`tool_error_guard`, classify shim) is untouched.

`prepare_arguments` is the per-tool repair hook (Pi convention): fix KNOWN model quirks
before validation, e.g. models calling `web_fetch` with `query=` instead of `url=`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    """One wire-facing tool: exposed name + JSON Schema + pointer to the legacy callable."""

    name: str
    legacy_name: str
    description: str
    parameters: dict = field(default_factory=dict)
    prepare_arguments: Callable[[dict], dict] | None = None

    def as_openai_tool(self) -> dict:
        """The `tools=[...]` entry shape for an OpenAI-compatible chat completion."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _schema(properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }


def _query_schema(desc: str) -> dict:
    return _schema({"query": {"type": "string", "description": desc}}, ["query"])


def _fix_web_fetch_args(args: dict) -> dict:
    """Models trained on `web_search(query=...)` sometimes call web_fetch the same way."""
    url = str(args.get("url") or args.get("query") or "").strip()
    return {"url": url} if url else {}


#: Registry: legacy toolset key → wire-facing spec. Order here is the order offered to the
#: model. Descriptions are one-liners on purpose — the system prompt stays proportional to
#: the ACTIVE toolset instead of carrying a hand-written contract block.
_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="web_search",
        legacy_name="web.search",
        description=(
            "Search the web. Returns result titles, URLs and snippets. "
            "Use short, specific keyword queries."
        ),
        parameters=_query_schema("Short specific search keywords."),
    ),
    ToolSpec(
        name="web_fetch",
        legacy_name="web.scrape",
        description=(
            "Fetch one web page by URL and return its content as markdown. "
            "Use after web_search to read a promising result in full."
        ),
        parameters=_schema(
            {"url": {"type": "string", "description": "Full http(s) URL of the page."}},
            ["url"],
        ),
        prepare_arguments=_fix_web_fetch_args,
    ),
    ToolSpec(
        name="confluence_page",
        legacy_name="confluence.page",
        description="Read one Confluence page by its page id.",
        parameters=_schema(
            {"page_id": {"type": "string", "description": "The Confluence page id."}},
            ["page_id"],
        ),
    ),
    ToolSpec(
        name="jira_issues",
        legacy_name="jira.issues",
        description="List currently open Jira issues for the team.",
        parameters=_schema(),
    ),
    ToolSpec(
        name="github_prs",
        legacy_name="github.prs",
        description="List currently open GitHub pull requests for the team.",
        parameters=_schema(),
    ),
    ToolSpec(
        name="linear_issues",
        legacy_name="linear.issues",
        description="List Linear issues for the team.",
        parameters=_schema(),
    ),
    ToolSpec(
        name="history_search",
        legacy_name="history.search",
        description=(
            "Search the team's own past work (delivered tasks, notes). "
            "Returns cited excerpts."
        ),
        parameters=_schema(
            {
                "query": {"type": "string", "description": "What to look for."},
                "days": {
                    "type": "integer",
                    "description": "Only look this many days back (0 = no limit).",
                },
                "agent": {
                    "type": "string",
                    "description": "Restrict to one agent id (empty = all).",
                },
            },
            ["query"],
        ),
    ),
    ToolSpec(
        name="gws_gmail",
        legacy_name="gws.gmail",
        description="Read the team Gmail inbox triage (recent unread/important mail).",
        parameters=_schema(),
    ),
    ToolSpec(
        name="gws_calendar",
        legacy_name="gws.calendar",
        description="Read the team calendar agenda (upcoming events).",
        parameters=_schema(),
    ),
    ToolSpec(
        name="gws_drive",
        legacy_name="gws.drive",
        description="List/search files in the team Google Drive.",
        parameters=_schema(
            {"query": {"type": "string", "description": "Optional file name/content filter."}},
        ),
    ),
)

_BY_LEGACY: dict[str, ToolSpec] = {s.legacy_name: s for s in _REGISTRY}


def _generic_spec(legacy_name: str) -> ToolSpec:
    """Forward-compat: an unregistered runtime tool keeps the old loop's one-string-query
    shape instead of silently disappearing from the model's tool menu."""
    return ToolSpec(
        name=legacy_name.replace(".", "_"),
        legacy_name=legacy_name,
        description=f"Tool {legacy_name}.",
        parameters=_schema(
            {"query": {"type": "string", "description": "Free-form input."}},
        ),
    )


def build_typed_specs(tools_map: dict[str, Callable[[dict], object]]) -> list[ToolSpec]:
    """Specs for exactly the tools this runtime actually has, in registry order.

    Tools present in `tools_map` but absent from the registry are appended last with a
    generic query schema (see `_generic_spec`).
    """
    specs = [spec for spec in _REGISTRY if spec.legacy_name in tools_map]
    known = {s.legacy_name for s in specs}
    specs.extend(_generic_spec(name) for name in tools_map if name not in known)
    return specs
