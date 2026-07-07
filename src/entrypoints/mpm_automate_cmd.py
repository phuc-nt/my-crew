"""`mpm agent automate <id> <automation.yaml> [--dry-run]` (v2 M3-P12 D3).

Runs a declarative workflow for one agent: chains whitelisted READ steps, runs `analyze`
steps via the agent's LLM (named prompts only), and PROPOSES writes by enqueueing them into
the agent's EXISTING Lớp B approval queue through the Action Gateway. A proposal is printed
with its `pending_approval` id so the operator can `mpm agent approve <id> <approval-id>`.
It NEVER prints "executed" — the engine never auto-runs a write.

`--dry-run` runs reads/analyze + resolves each proposal's action dict and PRINTS it, but
never calls the gateway (the ApprovalStore stays empty).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from src.entrypoints.mpm_manage_cmds import _load_agent
from src.runtime.registry import load_registry


def _build_read_tools(config) -> dict[str, Any]:
    """Map whitelisted read-tool names to config-bound callables taking the step args."""
    from src.tools import confluence_read, github_read, jira_read, linear_read

    return {
        "jira.issues": lambda args: jira_read.get_open_issues(config=config),
        "github.prs": lambda args: github_read.get_open_prs(config=config),
        "linear.issues": lambda args: linear_read.get_issues(config, args),
        "confluence.page": lambda args: confluence_read.get_page_content(
            args.get("page_id"), config=config
        ),
    }


def _build_analyze_fn(settings):
    """Return an analyze fn (named-prompt text, vars) -> summary via the agent's LLM."""
    from src.llm.client import LlmClient

    client = LlmClient(settings)

    def _analyze(prompt_text: str, variables: dict[str, Any]) -> str:
        # Message is a plain {"role","content"} dict in this codebase.
        content = f"Dữ liệu:\n{variables}"
        result = client.complete(
            [
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": content},
            ]
        )
        return result.content

    return _analyze


def run_automate(args: list[str], *, gateway=None, read_tools=None, analyze_fn=None) -> int:
    """Parse + run a workflow. Returns 0 on a clean run/plan, non-zero on error."""
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) < 2:
        print(
            "usage: mpm agent automate <id> <automation.yaml> [--dry-run]", file=sys.stderr
        )
        return 2
    agent_id, yaml_path = positional[0], positional[1]
    dry_run = "--dry-run" in args

    try:
        known = {e.id for e in load_registry()}
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if agent_id not in known:
        print(f"error: unknown agent {agent_id!r} (not in registry.yaml).", file=sys.stderr)
        return 1

    path = Path(yaml_path)
    if not path.exists():
        print(f"error: automation file not found: {yaml_path}", file=sys.stderr)
        return 1

    from src.automation.engine import run_workflow
    from src.automation.schema import parse_automation

    try:
        workflow = parse_automation(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ValueError, yaml.YAMLError) as exc:
        print(f"error: invalid automation.yaml: {exc}", file=sys.stderr)
        return 1

    loaded = _load_agent(agent_id)
    if loaded is None:
        return 1
    settings, config = loaded.settings, loaded.config

    gw = gateway or _default_gateway(settings, config)
    tools = read_tools if read_tools is not None else _build_read_tools(config)
    analyze = analyze_fn or _build_analyze_fn(settings)

    # v11 P3: an automation's `read` steps can each call an MCP tool (jira/confluence/
    # linear) — pool them into one spawn per server for this run, same as the scheduled
    # report/inbox/tasks runs. This CLI command runs on the main thread, so the
    # contextvar can be set directly around the call.
    from src.adapters.mcp_session_pool import McpSessionPool, _current_pool

    try:
        with McpSessionPool() as pool:
            token = _current_pool.set(pool)
            try:
                results = run_workflow(
                    workflow, read_tools=tools, analyze_fn=analyze, gateway=gw, dry_run=dry_run
                )
            finally:
                _current_pool.reset(token)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_results(workflow.name, results, dry_run)
    return 0


def _default_gateway(settings, config):
    from src.actions.action_gateway import ActionGateway

    return ActionGateway(settings, external_channels=config.slack_external_channels)


def _print_results(name: str, results, dry_run: bool) -> None:
    mode = " (dry-run)" if dry_run else ""
    print(f"workflow {name}{mode}:")
    for r in results:
        if r.kind == "propose" and dry_run:
            print(f"  propose [dry-run] would enqueue: {r.proposed}")
        elif r.kind == "propose":
            extra = f" approval_id={r.approval_id}" if r.approval_id is not None else ""
            print(f"  propose -> {r.status}{extra}")
        else:
            print(f"  {r.kind}: {r.detail}")
    if not dry_run and any(r.approval_id is not None for r in results):
        print("approve a proposal with: mpm agent approve <id> <approval-id>")
