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

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from my_crew.runtime.content_caps import (
    ERROR_MSG_CHARS,
    PAGE_CONTENT_CHARS,
    cap_with_footer,
)

if TYPE_CHECKING:
    from my_crew.config.reporting_config import ReportingConfig

logger = logging.getLogger(__name__)


class ToolPolicyError(RuntimeError):
    """A tool was refused by the policy shim (not a read tool, or classify blocked it)."""


#: Common secret-key prefixes (OpenAI/OpenRouter sk-, Slack xox-, GitHub ghp-, GitLab glpat-).
#: Provider error messages sometimes echo the offending key — scrub before it reaches the model.
_TOKEN_LIKE_RE = re.compile(r"\b(?:sk|xox[a-z]?|ghp|glpat)-[A-Za-z0-9_\-]{8,}")


def _short_error_text(exc: BaseException) -> str:
    """One bounded, control-char-free, secret-scrubbed line describing a tool failure."""
    msg = str(exc).strip() or exc.__class__.__name__
    msg = "".join(ch for ch in msg if ch == "\n" or ord(ch) >= 32)
    msg = _TOKEN_LIKE_RE.sub("***", msg)
    return msg[:ERROR_MSG_CHARS]


def _is_loop_control_exception(exc: BaseException) -> bool:
    """langgraph signals interrupt/bubble-up VIA exceptions — swallowing one would break
    resume/interrupt semantics, so the guard must let them propagate untouched."""
    try:
        from langgraph.errors import GraphBubbleUp
    except ImportError:  # toolset used outside a langgraph runtime — nothing to bubble
        return False
    return isinstance(exc, GraphBubbleUp)


def tool_error_guard(tool_name: str, fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
    """Wrap a tool callable so failures come back as short "⚠️" strings for the model.

    With the pinned langchain, only schema errors are fed back to the LLM; any exception
    from the tool BODY propagates and kills the whole graph invoke — one flaky network
    read would fail the step and discard the model's work. This guard converts failures
    into text the model can react to (retry differently, use another tool, answer from
    what it has). Two shapes on purpose: "bị từ chối" (policy block — do not retry) vs
    "lỗi" (transient — trying something else may work). Loop-control exceptions
    (GraphInterrupt & co.) and system BaseExceptions are re-raised, never swallowed.
    """

    def _safe(args: dict) -> Any:
        try:
            return fn(args)
        except ToolPolicyError as exc:
            logger.warning("tool %s refused by policy: %s", tool_name, exc)
            return f"⚠️ tool {tool_name} bị từ chối: {_short_error_text(exc)}"
        except Exception as exc:  # noqa: BLE001 — the whole point: degrade, don't kill the loop
            if _is_loop_control_exception(exc):
                raise
            logger.warning("tool %s failed: %s", tool_name, exc, exc_info=True)
            return f"⚠️ tool {tool_name} lỗi: {_short_error_text(exc)}"

    _safe.__name__ = tool_name.replace(".", "_")
    return _safe


#: Read tools whose output is INTERNAL-only (per-person workload, headcount, issue detail).
#: Withheld from external-audience runs so summarize/compose cannot leak them outward.
#: v39 #1: the Google Workspace reads (company mail/calendar/drive) are internal too.
_INTERNAL_ONLY_READS = frozenset(
    {"jira.issues", "linear.issues", "confluence.page", "history.search",
     "gws.gmail", "gws.calendar", "gws.drive"}
)


def _classify_ok(tool_name: str, args: dict) -> None:
    """Run the gateway's Lớp A/allowlist classify on a read call; raise if blocked.

    A read tool should never be a data-loss/credential/security action, so a block here means
    something is wrong (a mislabeled tool, a hostile arg) — fail loud rather than proceed.
    """
    from my_crew.actions.hard_block import classify

    verdict = classify({"type": "mcp_tool", "tool": tool_name, "args": args})
    # NOT_ALLOWLISTED is expected for read tools (they are not in the WRITE allowlist); only a
    # real Lớp A category (data-loss / credential / security) is a hard refusal here.
    cat = verdict.category.value if verdict.category is not None else None
    if verdict.blocked and cat is not None and cat != "not_allowlisted":
        raise ToolPolicyError(
            f"tool {tool_name!r} refused by policy: {cat} ({verdict.reason})"
        )


def _audit_read_call(
    tool_name: str, verdict: str, reason: str, elapsed_ms: int, outcome: str = "ok"
) -> None:
    """Record one read-tool call on the shared trail. Never raises.

    `outcome` ("ok" | "error") is what the tool BODY did, which the policy `verdict`
    cannot express: classify allows a call, then the fetch times out, and both rows read
    "allow". It rides in `result_summary` — an existing, already-redacted field no read
    row was using — so "which tool keeps failing" is answerable from the trail without a
    second writer or a schema change.

    The shim was already the single policy chokepoint; until now it was a chokepoint that
    kept no record, so a Lớp B audit could see writes but not the reads that informed
    them. Identity comes from the ambient `ToolCallContext` (see that module for why it
    is ambient), and lands in `params` rather than as new `AuditEntry` fields: task/step/
    iteration are meaningful for a team step and empty for every other caller, and the
    entry's top level is the schema every existing reader and dashboard filters on.

    Args are NOT recorded. They are attacker-influenced free text on a read path that now
    writes a row per call, and the trail has no rotation — `tool` plus the verdict is what
    an audit needs, and it is bounded.
    """
    from my_crew.audit.audit_log import AuditEntry, AuditLog
    from my_crew.runtime.team_task_paths import team_tasks_root
    from my_crew.runtime_backends.tool_call_context import current_tool_call_context

    ctx = current_tool_call_context()
    try:
        AuditLog(team_tasks_root() / "audit" / "audit.jsonl").record(
            AuditEntry(
                action_type="mcp_tool_read",
                tool=tool_name,
                verdict=verdict,
                reason=reason,
                params={
                    "task_id": ctx.task_id,
                    "step_id": ctx.step_id,
                    "iteration": ctx.iteration,
                    "elapsed_ms": elapsed_ms,
                },
                result_summary=outcome,
                actor=ctx.agent_id,
            )
        )
    except Exception:  # noqa: BLE001 — audit is observation; it must never fail a read
        logger.warning("read-tool audit write failed for %s", tool_name, exc_info=True)


def _shim(tool_name: str, fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
    """Wrap a read callable so every invocation passes through classify first, then the
    error guard — a policy block or a tool-body failure returns a "⚠️" string instead of
    raising through (and killing) the agent loop. Every call leaves one audit row, with
    the verdict classify actually reached."""

    def _guarded(args: dict) -> Any:
        started = time.monotonic()
        try:
            _classify_ok(tool_name, args or {})
        except ToolPolicyError as exc:
            _audit_read_call(tool_name, "deny", _short_error_text(exc),
                             int((time.monotonic() - started) * 1000))
            raise
        # A tool that raises is still recorded: classify allowed the call, so "allow" is
        # the honest POLICY verdict either way. What the body did is carried separately in
        # `outcome`, because a trail that cannot tell a served read from a failed one
        # cannot answer which tool is unreliable.
        outcome = "ok"
        try:
            return fn(args or {})
        except BaseException as exc:  # noqa: BLE001 — re-raised below; only classified here
            outcome = "ok" if _is_loop_control_exception(exc) else "error"
            raise
        finally:
            _audit_read_call(tool_name, "allow", "",
                             int((time.monotonic() - started) * 1000), outcome)

    return tool_error_guard(tool_name, _guarded)


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
    from my_crew.tools.firecrawl_tool import FirecrawlBlocked, FirecrawlConfig, scrape_url

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
        md = cap_with_footer(
            res.markdown, PAGE_CONTENT_CHARS,
            "Cần phần sau: scrape URL của mục/trang con sát nội dung cần, "
            "hoặc search với từ khoá cụ thể hơn.",
        )
        return f"# {res.title}\n(nguồn: {res.url})\n\n{md}"

    return _scrape


def _web_search_tool(settings: Any) -> Callable[[dict], Any] | None:
    """A `web.search` callable over Tavily/Brave, or None when no provider key is set.

    This is the loop-side twin of the native graph's pre-work search hook — same
    `web_search` engine (redact → fail-closed gate → provider → audit), same shared
    team-tasks audit trail, same spotlight formatting of the snippets. The difference
    is WHO issues the query: here the model asks mid-loop and can follow up (search →
    `web.scrape` a result URL → search again), where the native hook fires exactly once
    before the model ever speaks. Until this existed the loop could read a page it
    already knew about but had no way to FIND one — a researcher step on the loop tier
    could not answer "giá thuê văn phòng quận 1 là bao nhiêu" any better than native.

    Results are snippets-only from the provider (never a follow-up GET — that larger
    egress is `web.scrape`'s job, visibly and separately). Failures degrade to a short
    message string so the loop continues.
    """
    if settings is None:
        return None
    from my_crew.tools.web_search_tool import WebSearchConfig

    config = WebSearchConfig(
        tavily_api_key=getattr(settings, "tavily_api_key", None),
        brave_api_key=getattr(settings, "brave_api_key", None),
    )
    if not config.available():
        return None

    def _search(args: dict) -> str:
        query = str((args or {}).get("query") or "")
        if not query.strip():
            return "(web.search cần tham số query)"
        from my_crew.audit.audit_log import AuditLog
        from my_crew.runtime.team_task_paths import team_tasks_root
        from my_crew.tools.search_result_formatter import format_search_results
        from my_crew.tools.web_search_tool import web_search_outcome

        try:
            audit_log = AuditLog(team_tasks_root() / "audit" / "audit.jsonl")
            # Actor = the per-agent data_dir basename (agent_data_dir(<id>) layout) — the
            # audit row was previously actor-less, making searches unattributable.
            actor = Path(str(getattr(settings, "data_dir", ""))).name
            results, status = web_search_outcome(
                query, config=config, audit_log=audit_log, actor=actor,
            )
        except Exception as exc:  # noqa: BLE001 — search best-effort, never crash the loop
            return f"(tra cứu web lỗi: {exc})"
        if results:
            text, _count, _quarantined = format_search_results(results)
            return text
        # v75 silent-success guard, loop-tier mirror of the native hook's 3-path:
        # "the web says nothing" vs "we never reached the web" are opposite THIẾU
        # reasons and the model must see which one happened.
        if status == "provider_error":
            return ("[LỖI NGUỒN TÌM KIẾM] Không truy cập được web search (nhà cung "
                    "cấp lỗi/timeout). Phần dữ liệu này ghi THIẾU DO NGUỒN LỖI — "
                    "KHÔNG kết luận 'dữ liệu không tồn tại'.")
        return ("[KHÔNG CÓ KẾT QUẢ] Nguồn tìm kiếm hoạt động bình thường nhưng không "
                "có kết quả cho truy vấn này — thử từ khoá khác ngắn và cụ thể hơn; "
                "nếu vẫn không có, ghi THIẾU vì dữ liệu không có công khai.")

    return _search


def _gws_tool(surface: str) -> Callable[[dict], Any]:
    """A Google Workspace READ callable (`gmail`/`calendar`/`drive`) over the gws CLI.

    Wraps the result in the internal-content guard (company data) and degrades a CLI/OAuth
    failure to a short string — the loop continues. The read argv is CODE-fixed inside
    `gws_read`; only a `query` param (drive) is passed through, never an argv.
    """

    def _read(args: dict) -> str:
        from my_crew.tools.gws_read import (
            GwsReadError,
            calendar_agenda,
            drive_list,
            gmail_triage,
        )
        from my_crew.tools.search_result_formatter import format_internal_content

        try:
            if surface == "gmail":
                raw = gmail_triage()
            elif surface == "calendar":
                raw = calendar_agenda()
            else:  # drive
                raw = drive_list(str((args or {}).get("query") or ""))
        except GwsReadError as exc:
            return f"(gws {surface} lỗi: {exc})"
        return format_internal_content(raw, label=f"gws {surface}")

    return _read


def _history_search_tool() -> Callable[[dict], Any]:
    """A `history.search` callable over the team's own past work (v33 P5).

    args: {query, days?, agent?}. Returns cited excerpts (task:seq / audit ts) for
    the LLM to summarize WITH sources — never a raw dump (results are capped at the
    index layer). Failures degrade to a short message string, like every read tool.
    """

    def _search(args: dict) -> str:
        query = str((args or {}).get("query") or "")
        if not query.strip():
            return "(history.search cần tham số query)"
        from my_crew.runtime.history_search_index import HistorySearchIndex
        from my_crew.tools.search_result_formatter import format_internal_content

        try:
            idx = HistorySearchIndex()
            try:
                idx.sweep()  # opportunistic freshness — incremental, cheap when idle
                hits = idx.search(
                    query,
                    days=int((args or {}).get("days") or 0),
                    agent=str((args or {}).get("agent") or ""),
                )
            finally:
                idx.close()
        except Exception as exc:  # noqa: BLE001 — search best-effort, never crash the loop
            return f"(tìm lịch sử lỗi: {exc})"
        if not hits:
            return "(không tìm thấy gì trong lịch sử làm việc)"
        lines = [
            f"- [{h['source']} {h['ref']} · {h['agent_id']} · {h['ts'][:10]}] {h['excerpt']}"
            for h in hits
        ]
        return format_internal_content("\n".join(lines), label="kết quả tìm lịch sử")

    return _search


def build_read_toolset(
    config: ReportingConfig, audience: str = "internal", settings: Any = None,
    gws_context: bool = False, web_search: bool = False,
) -> dict[str, Callable[[dict], Any]]:
    """The positive read-allowlist for a tool-calling runtime, policy-shimmed + audience-aware.

    Returns a name→callable map. External audience drops internal-only reads. Every callable is
    shimmed through `classify`. There is no path here to a write/destructive tool — they are
    not listed. `settings` (optional) enables the Firecrawl web-scrape tool when configured.
    `gws_context` (v39 #1) enables the Google Workspace READ tools (Gmail/Calendar/Drive) —
    INTERNAL company data, so internal-audience only, and OFF by default (byte-identical).
    `web_search` (v73) enables the in-loop Tavily/Brave search — the same per-agent profile
    flag that gates the native pre-work hook, so one opt-in covers both tiers; OFF by
    default and additionally requires a provider key (byte-identical when absent).
    """
    raw: dict[str, Callable[[dict], Any]] = {}
    if config is not None:
        from my_crew.tools import confluence_read, github_read, jira_read, linear_read

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
    # v73: Tavily/Brave web search INSIDE the loop — gated on the same per-agent
    # `web_search:` profile flag the native pre-work hook uses (one opt-in, both tiers)
    # plus a provider key. Public snippets, both audiences, like web.scrape.
    if web_search:
        ws = _web_search_tool(settings)
        if ws is not None:
            raw["web.search"] = ws
    # v39 #1: Google Workspace READ (Gmail/Calendar/Drive) via the gws CLI — INTERNAL
    # company context, flag-gated per agent (default OFF ⇒ toolset byte-identical). Each
    # tool degrades to a "(gws … lỗi)" string on CLI/OAuth failure; the read argv is
    # CODE-fixed (LLM supplies only a query param), never a write.
    # `gws_enabled: false` dominates: it is the per-agent master switch for Google data,
    # so it has to close THIS door too. `gws_context` alone would otherwise hand the tool
    # loop a strictly LARGER surface than the snapshot gate closes — the snapshot never
    # exposed Drive at all.
    if gws_context and getattr(config, "gws_enabled", True):
        raw["gws.gmail"] = _gws_tool("gmail")
        raw["gws.calendar"] = _gws_tool("calendar")
        raw["gws.drive"] = _gws_tool("drive")
    # v33 P5: history search over the team's own past work (steps + audit). Internal
    # company data by nature → listed in _INTERNAL_ONLY_READS; always on for internal
    # audiences (read-only, no key, no network).
    raw["history.search"] = _history_search_tool()
    if audience != "internal":
        raw = {name: fn for name, fn in raw.items() if name not in _INTERNAL_ONLY_READS}
    return {name: _shim(name, fn) for name, fn in raw.items()}


def assert_read_only(tool_names: list[str]) -> None:
    """Raise if any name is a known write/destructive tool (adversarial-config guard).

    Used by tests + at runtime-build to prove the toolset never contains a mutation tool. Keys
    off the pack WRITE allowlists (the positive write permit-lists) PLUS an explicit destructive
    denylist so tools absent from the write allowlist (deletePage/deleteIssue) are also caught.
    """
    from my_crew.actions import hard_block

    destructive = {
        "deletepage", "deleteissue", "deleteboard", "deletebranch", "deletecomment",
    }
    write_markers: set[str] = set()
    # The pack allowlist is keyed by SERVER (slack/confluence/...) with the permitted WRITE tool
    # NAMES in the values — collect those names; any of them = a mutation, reject.
    for domain in ("pm", "hr", "admin", "office"):
        try:
            from my_crew.packs.registry import PackRegistry

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
