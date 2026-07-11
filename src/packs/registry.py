"""`Pack` + `PackRegistry`: the seam that loads a domain's pieces for the core.

`Pack` is the resolved bundle of one domain's contributions. `PackRegistry.load(domain)`
returns the pack for a domain string (the value of `profile.yaml`'s `domain:`, default
`"pm"`). In S1 this is scaffolding: the registry knows the set of valid domains but each
`Pack` carries empty collections, so the core still runs through its existing hardcoded
PM paths. Subsequent M5 slices fill the pack fields and switch the core to read them.

`report_kinds` maps a report-kind string (`"daily"`, `"weekly"`, `"okr"`, `"resource"`,
or a future domain's kinds) to the callable that builds its graph — replacing the
`if/elif kind` ladder in `runtime/worker.py` (S2). The remaining fields back the other
two seams (ToolProvider in S3, allowlist/write handlers in S4) and pack assets
(prompts/skills in S5); they stay empty until those slices move the code in.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from src.config.settings import REPO_ROOT

logger = logging.getLogger(__name__)

#: A report-kind graph builder, called uniformly by the core:
#: build(checkpointer, *, config, settings, context, audience, store, remember).
GraphBuilder = Callable[..., Any]

#: The default domain for any profile that does not declare `domain:` — keeps every
#: pre-v3 (PM) profile loading and dispatching exactly as before.
DEFAULT_DOMAIN = "pm"

#: Where in-repo packs live (✅ CHỐT 2026-06-30: in-repo folder, not a plugin
#: entry-point). A domain `x` resolves to `domain-packs/x-pack/`.
_PACKS_DIR = REPO_ROOT / "domain-packs"

#: A `graphs.py` is the marker of a real pack folder (every pack has one). Discovery
#: keys off it so an empty/partial dir is not mistaken for a domain.
_PACK_MARKER = "graphs.py"


def pack_dir(domain: str) -> Path:
    """Absolute path to a domain's pack folder (`domain-packs/<domain>-pack/`)."""
    return _PACKS_DIR / f"{(domain or DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN}-pack"


def discover_domains() -> tuple[str, ...]:
    """The domains that have a real pack on disk — `domain-packs/<x>-pack/graphs.py`.

    v3 M6: pack discovery is filesystem-based, so adding a new domain is dropping a
    `<x>-pack/` folder — NO core edit (this is what makes M6's `git diff src/` = empty
    gate reachable). An unknown domain (no folder) still fails loudly in `load()`, so
    default-DENY holds: a typo'd `domain:` never silently runs as PM.
    """
    if not _PACKS_DIR.exists():
        return (DEFAULT_DOMAIN,)
    found = sorted(
        p.name[: -len("-pack")]
        for p in _PACKS_DIR.iterdir()
        if p.is_dir() and p.name.endswith("-pack") and (p / _PACK_MARKER).exists()
    )
    return tuple(found)


def all_report_kinds() -> frozenset[str]:
    """Every report kind served by any installed pack (the union across domains).

    Used by the CLI/API to validate `--report` without hardcoding PM's kinds — a kind
    is valid if some pack serves it, so a new pack's kind (HR `headcount`) is accepted
    with no core edit. The per-agent worker still enforces that the agent's OWN pack
    serves the kind, so this union only gates obvious typos early.
    """
    registry = PackRegistry()
    kinds: set[str] = set()
    for domain in registry.known_domains():
        try:
            kinds.update(registry.load(domain).report_kinds)
        except Exception:  # noqa: BLE001
            # A broken/partial pack must not block kind-validation for every agent —
            # skip it and let the healthy packs' kinds through. The per-agent worker
            # still fails loudly for an agent whose own pack is broken.
            logger.warning("skipping pack %r in kind union: failed to load", domain, exc_info=True)
    return frozenset(kinds)


def pack_skills_dir(domain: str) -> Path:
    """Where a domain bundles its skill `.md` files (v3 M5 S5 pack asset)."""
    return pack_dir(domain) / "skills"


def profile_skills_dir(profile_id: str, *, profiles_dir: Path | None = None) -> Path:
    """Where an agent keeps its OWN skill `.md` files (v19 workspace protocol).

    Per-agent skills live in `profiles/<id>/skills/` (user-data, gitignored). They are a
    LOWER trust tier than pack skills (repo-vetted): their bodies are wrapped through the
    internal-content guard before entering the prompt (see `load_agent_skills`).
    """
    base = profiles_dir if profiles_dir is not None else (REPO_ROOT / "profiles")
    return base / profile_id / "skills"


def pack_prompts_dir(domain: str) -> Path:
    """Where a domain bundles its system-prompt `.md` files (v3 M5 S5 pack asset)."""
    return pack_dir(domain) / "prompts"


def load_pack_prompt(domain: str, name: str) -> str:
    """Read a pack's `prompts/<name>.md` verbatim (the system-prompt text asset).

    The PM message-builders moved their system-prompt STRINGS into pack assets in S5
    (the builder logic stays in core). The `.md` holds the exact prompt text — read
    raw, no trimming, so the composed prompt is byte-identical to the pre-v3 literal.
    """
    return (pack_prompts_dir(domain) / f"{name}.md").read_text(encoding="utf-8")


def _scan_pack_prompts(domain: str) -> dict[str, str]:
    """Load every `prompts/<name>.md` a pack ships → {name: text} (verbatim)."""
    pdir = pack_prompts_dir(domain)
    if not pdir.exists():
        return {}
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(pdir.glob("*.md"))}


def _scan_pack_skill_names(domain: str) -> tuple[str, ...]:
    """The skill `.md` filenames (stems) a pack bundles — for introspection/UI.

    Filename stems, not parsed `name:` fields (that parse lives in skill_loader); this
    is a cheap listing so a Pack advertises what skills it ships without a full load.
    """
    skills_dir = pack_skills_dir(domain)
    if not skills_dir.exists():
        return ()
    return tuple(sorted(p.stem for p in skills_dir.glob("*.md")))


def _pack_package_name(domain: str) -> str:
    """A valid Python package name for a pack (folder is hyphenated, not importable).

    `hr-pack` on disk ⇒ the importable package `domain_pack_hr`, so a pack's own modules
    can import siblings (`from domain_pack_hr.analyzers import ...`) — which PM never
    needed (its builders call src.* only) but a self-contained pack like HR does.
    """
    return f"domain_pack_{domain}"


def _ensure_pack_package(domain: str) -> None:
    """Register `domain-packs/<domain>-pack/` as an importable package in sys.modules.

    Idempotent. Sets the package `__path__` to the pack folder so `import
    domain_pack_<domain>.<mod>` resolves the pack's sibling modules. This is the generic
    mechanism that lets a pack be self-contained; it adds no domain knowledge to core.
    """
    pkg = _pack_package_name(domain)
    if pkg in sys.modules:
        return
    pack_root = _PACKS_DIR / f"{domain}-pack"
    if not (pack_root / _PACK_MARKER).exists():
        raise ImportError(f"No pack for domain {domain!r} at {pack_root}.")
    spec = importlib.util.spec_from_file_location(
        pkg, pack_root / "__init__.py", submodule_search_locations=[str(pack_root)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[pkg] = module
    # A pack need not ship an __init__.py; if it does, exec it, else leave the namespace.
    if spec.loader is not None and (pack_root / "__init__.py").exists():
        spec.loader.exec_module(module)


def _load_pack_module(domain: str, module_name: str) -> ModuleType:
    """Import a pack's `<module_name>.py` as `domain_pack_<domain>.<module_name>`.

    Registers the pack as a package first (so sibling imports work), then imports the
    submodule normally. The module can `import src.*` (repo root on sys.path) and
    `from domain_pack_<domain>.<other> import ...` (the package registered here).
    """
    _ensure_pack_package(domain)
    path = _PACKS_DIR / f"{domain}-pack" / f"{module_name}.py"
    if not path.exists():
        raise ImportError(f"Pack module not found: {path} (domain {domain!r}).")
    qualified = f"{_pack_package_name(domain)}.{module_name}"
    spec = importlib.util.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load pack module {path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Pack:
    """One domain's resolved contributions to the otherwise-generic core.

    All collections default empty so an as-yet-unpopulated pack is inert: the core
    keeps using its existing hardcoded path until a slice moves that seam onto the
    pack. Fields are filled across M5 — `report_kinds` (S2), `tools` (S3),
    `allowlist` (S4), `prompts`/`skills` (S5).

    Note: write-handler DISPATCH stays in core (`approved_dispatch.py`) — slack/linear/
    email are cross-domain shared primitives a pack reuses rather than owns — so a pack
    contributes only its `allowlist`, not handler callables. If a future domain needs a
    domain-specific handler, add a `write_handlers` field then (YAGNI here).
    """

    domain: str
    report_kinds: dict[str, GraphBuilder] = field(default_factory=dict)
    # ToolProvider (S3): how this domain reads its source systems. `Any` until the
    # interface lands in `src/packs/tool_provider.py` and S3 binds the PM provider.
    tools: Any | None = None
    # Allowlist contribution (S4): the MCP server→tool names this pack may write to.
    # Merged into the gateway's default-DENY allowlist; never widens the Lớp A red line.
    allowlist: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Pack assets (S5): prompt texts by logical name, and the bundled skill .md pool.
    prompts: dict[str, str] = field(default_factory=dict)
    skills: tuple[str, ...] = ()
    # v5 M12: chat-command catalog — the ONLY actions a chat mention may request.
    # Validated at load against the pack's own allowlist + Lớp A (see _load_commands):
    # a catalog can never name a red-line or non-allowlisted tool. Empty ⇒ the pack's
    # agents answer questions only (M11 behavior).
    commands: dict[str, dict] = field(default_factory=dict)


class PackRegistry:
    """Resolves a domain string to its `Pack`.

    S1 returns an empty `Pack(domain)` for any known domain — enough to thread the
    concept through the core without changing behavior. Later slices register real
    builders/tools/handlers per domain here (or have each pack self-register).
    """

    def __init__(self, known_domains: tuple[str, ...] | None = None) -> None:
        # None ⇒ discover from disk (the normal path). An explicit tuple is for tests
        # that want to pin the domain set without touching the filesystem.
        self._known = known_domains

    def known_domains(self) -> tuple[str, ...]:
        return self._known if self._known is not None else discover_domains()

    def load(self, domain: str | None) -> Pack:
        """Return the pack for `domain` (None/blank ⇒ the default PM domain).

        Raises ValueError for an unrecognized domain so a typo'd `domain:` fails
        loudly rather than silently running as PM. Populates the pack's report-kind
        builders from the pack's `graphs.py` (S2); the remaining seams (tools,
        allowlist, prompts, skills) are filled from the pack's other modules/assets.
        """
        resolved = (domain or DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN
        known = self.known_domains()
        if resolved not in known:
            raise ValueError(
                f"Unknown domain {resolved!r}: no pack registered. "
                f"Known domains: {', '.join(known)}."
            )
        graphs = _load_pack_module(resolved, "graphs")
        report_kinds: dict[str, GraphBuilder] = dict(getattr(graphs, "REPORT_KINDS", {}))
        tools_mod = _load_pack_module(resolved, "tools")
        tools = getattr(tools_mod, "TOOL_PROVIDER", None)
        wh = _load_pack_module(resolved, "write_handlers")
        allowlist: dict[str, tuple[str, ...]] = dict(getattr(wh, "ALLOWLIST", {}))
        skills = _scan_pack_skill_names(resolved)
        prompts = _scan_pack_prompts(resolved)
        commands = _load_commands(resolved, allowlist)
        return Pack(
            domain=resolved, report_kinds=report_kinds, tools=tools,
            allowlist=allowlist, skills=skills, prompts=prompts, commands=commands,
        )


def _load_commands(domain: str, allowlist: dict[str, tuple[str, ...]]) -> dict[str, dict]:
    """Load a pack's optional chat-command catalog (`commands.py:COMMANDS`) — validated.

    FAIL-LOUD at load if any command names a tool the pack's own allowlist + Lớp A
    would not permit: the catalog is the ceiling of what chat can request, so a
    red-line tool must be impossible to even declare, not merely denied later.
    """
    if not (pack_dir(domain) / "commands.py").exists():
        return {}
    module = _load_pack_module(domain, "commands")
    commands = dict(getattr(module, "COMMANDS", {}))
    if not commands:
        # A commands.py that exports nothing is a typo'd catalog, not "no catalog" —
        # deleting the file is how a pack opts out. Fail loud, don't silently disable.
        raise RuntimeError(f"pack {domain!r} has commands.py but exports no COMMANDS")
    from src.actions.hard_block import classify

    for command_id, spec in commands.items():
        build_args = spec.get("build_args")
        if build_args is not None and not callable(build_args):
            raise RuntimeError(
                f"pack {domain!r} command {command_id!r}: build_args must be callable "
                "— it is the hook that confines requester args (e.g. pins projectKey)."
            )
        probe = {
            "type": "mcp_tool",
            "server": str(spec.get("server", "")),
            "tool": str(spec.get("tool", "")),
            "args": {},
        }
        verdict = classify(probe, allowlist=allowlist)
        if verdict.blocked:
            raise RuntimeError(
                f"pack {domain!r} command {command_id!r} names a forbidden tool "
                f"{probe['server']}:{probe['tool']} ({verdict.category}): {verdict.reason}"
            )
    return commands
