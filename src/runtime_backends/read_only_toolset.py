"""Read-only toolset + policy shim for tool-calling runtimes (v20 Phase 2).

THE INVARIANT this file enforces (red-team C1/C2/H4):

- **Positive allowlist, never a denylist.** The loop is given an EXPLICIT list of read-only
  callables (mirrors `mpm_automate_cmd._build_read_tools`), not "every MCP tool minus the write
  allowlist" — the write allowlist is a positive permit-list of ~11 named writes, so its
  complement still contains destructive tools like `deletePage`/`deleteIssue`. Those must NEVER
  enter the toolset; here they simply are not listed.
- **Policy shim on every tool.** Each callable is wrapped so it runs `hard_block.classify`
  before doing anything. Even though the toolset is read-only by construction, the shim keeps
  the gateway's classify as the single policy chokepoint — a defense-in-depth so a future tool
  that slips in still cannot reach a side effect without being classified.
- **Audience-aware.** For an `external` audience run, internal-data read tools are withheld
  entirely, so a summarize step cannot fold internal content into an external deliverable.

The runtime that consumes this (`ToolCallingRuntime`) never binds raw MCP tools to the model;
it binds only what `build_read_toolset` returns.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config.reporting_config import ReportingConfig


class ToolPolicyError(RuntimeError):
    """A tool was refused by the policy shim (not a read tool, or classify blocked it)."""


#: Read tools whose output is INTERNAL-only (per-person workload, headcount, issue detail).
#: Withheld from external-audience runs so summarize/compose cannot leak them outward.
_INTERNAL_ONLY_READS = frozenset({"jira.issues", "linear.issues", "confluence.page"})


def _classify_ok(tool_name: str, args: dict) -> None:
    """Run the gateway's Lớp A/allowlist classify on a read call; raise if blocked.

    A read tool should never be a data-loss/credential/security action, so a block here means
    something is wrong (a mislabeled tool, a hostile arg) — fail loud rather than proceed.
    """
    from src.actions.hard_block import classify

    verdict = classify({"type": "mcp_tool", "tool": tool_name, "args": args})
    # NOT_ALLOWLISTED is expected for read tools (they are not in the WRITE allowlist); only a
    # real Lớp A category (data-loss / credential / security) is a hard refusal here.
    cat = verdict.category.value if verdict.category is not None else None
    if verdict.blocked and cat is not None and cat != "not_allowlisted":
        raise ToolPolicyError(
            f"tool {tool_name!r} refused by policy: {cat} ({verdict.reason})"
        )


def _shim(tool_name: str, fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
    """Wrap a read callable so every invocation passes through classify first."""

    def _guarded(args: dict) -> Any:
        _classify_ok(tool_name, args or {})
        return fn(args or {})

    _guarded.__name__ = tool_name.replace(".", "_")
    return _guarded


#: Cap on scraped markdown fed back into the loop (untrusted web content — keep it bounded).
_SCRAPE_MAX_CHARS = 8000


def _firecrawl_tool(settings: Any) -> Callable[[dict], Any] | None:
    """A `web.scrape` callable backed by Firecrawl, or None when Firecrawl is not configured.

    The returned callable takes `{"url": ...}`, SSRF-guards + scrapes it, and returns bounded
    markdown. Firecrawl errors (offline, blocked target, bad URL) degrade to a short message
    string — the loop continues without crashing. The content is UNTRUSTED; the runtime's own
    result_text still goes through the internal-content wrap before any downstream prompt use.
    """
    if settings is None:
        return None
    base = getattr(settings, "firecrawl_base_url", None)
    if not base:
        return None
    from src.tools.firecrawl_tool import FirecrawlBlocked, FirecrawlConfig, scrape_url

    fc = FirecrawlConfig(base_url=base, api_key=getattr(settings, "firecrawl_api_key", None))

    def _scrape(args: dict) -> str:
        url = (args or {}).get("url") or (args or {}).get("query") or ""
        if not url:
            return "(web.scrape cần tham số url)"
        try:
            res = scrape_url(url, fc)
        except FirecrawlBlocked as exc:
            return f"(bị chặn: {exc})"
        except Exception as exc:  # noqa: BLE001 — scrape best-effort, never crash the loop
            return f"(scrape lỗi: {exc})"
        md = res.markdown[:_SCRAPE_MAX_CHARS]
        return f"# {res.title}\n(nguồn: {res.url})\n\n{md}"

    return _scrape


def _openalex_tool() -> Callable[[dict], Any]:
    """An `academic.search` callable over OpenAlex (public data, no key, fixed host).

    Provider/network failures degrade to a short message string — the loop continues.
    The rendered results are untrusted-wrapped by `render_works` itself.
    """

    def _search(args: dict) -> str:
        query = str((args or {}).get("query") or "")
        if not query.strip():
            return "(academic.search cần tham số query)"
        from src.tools.openalex_tool import render_works, search_works

        try:
            works = search_works(query)
        except Exception as exc:  # noqa: BLE001 — search best-effort, never crash the loop
            return f"(tra cứu OpenAlex lỗi: {exc})"
        return render_works(works)

    return _search


def build_read_toolset(
    config: ReportingConfig, audience: str = "internal", settings: Any = None,
    academic_search: bool = False,
) -> dict[str, Callable[[dict], Any]]:
    """The positive read-allowlist for a tool-calling runtime, policy-shimmed + audience-aware.

    Returns a name→callable map. External audience drops internal-only reads. Every callable is
    shimmed through `classify`. There is no path here to a write/destructive tool — they are
    not listed. `settings` (optional) enables the Firecrawl web-scrape tool when configured;
    `academic_search` (the per-agent profile flag, v31 P6) enables OpenAlex — keyless, so the
    flag is its only gate and the default keeps every existing toolset byte-identical.
    """
    raw: dict[str, Callable[[dict], Any]] = {}
    if config is not None:
        from src.tools import confluence_read, github_read, jira_read, linear_read

        raw = {
            "jira.issues": lambda args: jira_read.get_open_issues(config=config),
            "github.prs": lambda args: github_read.get_open_prs(config=config),
            "linear.issues": lambda args: linear_read.get_issues(config, args),
            "confluence.page": lambda args: confluence_read.get_page_content(
                args.get("page_id"), config=config
            ),
        }
    # v20.5: Firecrawl web-scrape (fetch a URL → markdown). READ-only + SSRF-guarded at source.
    # Available on both audiences (it fetches PUBLIC web pages, not internal company data) when
    # FIRECRAWL_BASE_URL is set; absent ⇒ the tool is simply not offered (degrade, no crash).
    fc = _firecrawl_tool(settings)
    if fc is not None:
        raw["web.scrape"] = fc
    # v31 P6: OpenAlex paper search — public academic data, both audiences, flag-gated.
    if academic_search:
        raw["academic.search"] = _openalex_tool()
    if audience != "internal":
        raw = {name: fn for name, fn in raw.items() if name not in _INTERNAL_ONLY_READS}
    return {name: _shim(name, fn) for name, fn in raw.items()}


def assert_read_only(tool_names: list[str]) -> None:
    """Raise if any name is a known write/destructive tool (adversarial-config guard).

    Used by tests + at runtime-build to prove the toolset never contains a mutation tool. Keys
    off the pack WRITE allowlists (the positive write permit-lists) PLUS an explicit destructive
    denylist so tools absent from the write allowlist (deletePage/deleteIssue) are also caught.
    """
    from src.actions import hard_block

    destructive = {
        "deletepage", "deleteissue", "deleteboard", "deletebranch", "deletecomment",
    }
    write_markers: set[str] = set()
    # The pack allowlist is keyed by SERVER (slack/confluence/...) with the permitted WRITE tool
    # NAMES in the values — collect those names; any of them = a mutation, reject.
    for domain in ("pm", "hr", "admin", "office"):
        try:
            from src.packs.registry import PackRegistry

            pack = PackRegistry().load(domain)
            for tools in (pack.allowlist or {}).values():
                write_markers.update(t.lower() for t in tools)
        except Exception:  # noqa: BLE001 — a missing pack must not weaken the guard
            continue
    for name in tool_names:
        low = name.lower().replace("_", "").replace(".", "")
        marker = name.lower().replace(".", "_")
        is_write = marker in write_markers or name.lower() in write_markers
        if any(d in low for d in destructive) or is_write:
            raise ToolPolicyError(f"tool {name!r} is a write/destructive tool — not read-only.")
    _ = hard_block  # keep the classify module import-coupled for clarity
