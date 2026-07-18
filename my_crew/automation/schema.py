"""Workflow schema + strict parser for `automation.yaml` (v2 M3-P12 D3).

A flat, linear workflow — NO DAG, NO branching, NO loops, NO parallelism (YAGNI). Three
step types only: `read`, `analyze`, `propose`. A single optional top-level `when` gate
(one `field == value` comparison; no boolean operators, no eval). Everything is validated
at parse time and fails CLOSED — an unknown step type / read tool / propose target / prompt
name raises a clear error rather than silently doing something.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from my_crew.automation.prompts import is_known_prompt

# Whitelist: a `read:` step may only name one of these `<module>.<entity>` reads. The
# engine maps each to a real read function; an unlisted name is a parse error (no arbitrary
# import from yaml). Reads bypass the gateway by design (they are non-mutating).
READ_TOOLS: frozenset[str] = frozenset(
    {
        "jira.issues",
        "github.prs",
        "linear.issues",
        "confluence.page",
    }
)

# Whitelist: a `propose:` step may only target one of these. Each maps to a Lớp B action
# dict shape that mirrors an existing report writer. NO gh_cli / destructive proposes.
PROPOSE_TARGETS: frozenset[str] = frozenset({"slack.post", "linear.comment"})


@dataclass(frozen=True)
class ReadStep:
    tool: str
    args: dict[str, Any]
    bind: str  # `as:` — name to store the result under in the context


@dataclass(frozen=True)
class AnalyzeStep:
    prompt: str  # a NAMED prompt (validated against the registry)
    using: tuple[str, ...]  # context names fed to the prompt
    bind: str


@dataclass(frozen=True)
class ProposeStep:
    target: str  # one of PROPOSE_TARGETS
    args: dict[str, Any]  # may contain {{var}} templates resolved at run time


@dataclass(frozen=True)
class Condition:
    field: str
    value: str


@dataclass(frozen=True)
class Workflow:
    name: str
    when: Condition | None
    steps: tuple[Any, ...]  # ReadStep | AnalyzeStep | ProposeStep


def _parse_when(raw: Any) -> Condition | None:
    """Parse the single-comparison `when` (`field == value`). None when absent.

    LOCKED to ONE `==` comparison. A multi-operator / malformed condition raises — no
    boolean operators, no eval, no expression language.
    """
    if raw is None:
        return None
    if not isinstance(raw, str) or "==" not in raw:
        raise ValueError(f"when must be a single 'field == value' comparison, got {raw!r}")
    # Reject compound conditions explicitly (only ONE comparison allowed).
    if raw.count("==") != 1 or any(op in raw for op in (" and ", " or ", "!=", ">=", "<=")):
        raise ValueError(f"when supports only a single '==' comparison, got {raw!r}")
    field, value = (part.strip() for part in raw.split("==", 1))
    if not field or not value:
        raise ValueError(f"when has an empty field or value: {raw!r}")
    return Condition(field=field, value=value.strip("'\""))


def _parse_step(raw: dict[str, Any]) -> Any:
    if not isinstance(raw, dict):
        raise ValueError(f"each step must be a mapping, got {type(raw).__name__}")
    if "read" in raw:
        tool = str(raw["read"])
        if tool not in READ_TOOLS:
            raise ValueError(f"unknown read tool {tool!r}; allowed: {sorted(READ_TOOLS)}")
        bind = raw.get("as")
        if not bind:
            raise ValueError(f"read step {tool!r} needs an `as:` binding name")
        return ReadStep(tool=tool, args=dict(raw.get("args") or {}), bind=str(bind))
    if "analyze" in raw:
        # The `analyze:` value IS the named prompt (parallels read:/propose: where the
        # value names the target). No free-text prompt body — registry-validated.
        prompt = str(raw["analyze"])
        if not is_known_prompt(prompt):
            raise ValueError(f"unknown analyze prompt {prompt!r} (named prompts only)")
        bind = raw.get("as")
        if not bind:
            raise ValueError("analyze step needs an `as:` binding name")
        using = tuple(str(u) for u in (raw.get("using") or ()))
        return AnalyzeStep(prompt=prompt, using=using, bind=str(bind))
    if "propose" in raw:
        target = str(raw["propose"])
        if target not in PROPOSE_TARGETS:
            raise ValueError(
                f"unknown propose target {target!r}; allowed: {sorted(PROPOSE_TARGETS)}"
            )
        return ProposeStep(target=target, args=dict(raw.get("args") or {}))
    raise ValueError(f"step has no known type (read|analyze|propose): {sorted(raw)}")


def parse_automation(yaml_doc: dict[str, Any]) -> Workflow:
    """Validate + parse a workflow doc into a frozen `Workflow`. Fails closed on any error."""
    if not isinstance(yaml_doc, dict):
        raise ValueError("automation.yaml must be a mapping at the top level")
    name = yaml_doc.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("automation.yaml requires a non-empty string `name`")
    raw_steps = yaml_doc.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("automation.yaml requires a non-empty `steps` list")
    steps = tuple(_parse_step(s) for s in raw_steps)
    return Workflow(name=name, when=_parse_when(yaml_doc.get("when")), steps=steps)
