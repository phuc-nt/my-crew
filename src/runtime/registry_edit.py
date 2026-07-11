"""Shared registry.yaml + profile-dir mutations (v3 M7).

One home for every write to `registry.yaml` and for profile scaffolding, so the CLI
(`mpm agent register`) and the web create/lifecycle API mutate the SAME way (DRY) and
every edit is validate-before-replace: the new text is parsed with `load_registry` on a
temp file FIRST; only a clean parse (and the expected post-condition) is `os.replace`d
over the real file. A bad edit raises and leaves the original byte-unchanged — the same
contract `profile_editor.save_profile_yaml` gives profile.yaml.

Text surgery (not yaml.dump) keeps the file's comments — registry.yaml is committed and
its header comments are documentation.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from pathlib import Path

from src.runtime.registry import _REGISTRY_PATH, load_registry

#: One process-wide lock for every registry.yaml mutation: the web admin routes run in
#: a threadpool, so two concurrent edits (double-clicked toggle, create racing delete)
#: would otherwise interleave read→replace and lose one update.
_EDIT_LOCK = threading.Lock()

_PLACEHOLDER_MD = {
    "SOUL.md": "<!-- Persona. Empty ⇒ the v1 system prompt is used unchanged. -->\n",
    "PROJECT.md": "<!-- Project context. Empty ⇒ no extra context added. -->\n",
    "MEMORY.md": "<!-- Agent memory. Empty by default; read verbatim into context. -->\n",
}


class UnknownRegistryAgentError(KeyError):
    """The agent id has no entry in registry.yaml."""


def scaffold_profile_dir(
    profiles_dir: Path,
    agent_id: str,
    *,
    profile_yaml_text: str | None = None,
    soul_md: str | None = None,
) -> Path:
    """Create profiles/<id>/ from the default template + placeholder md files.

    `profile_yaml_text` (web create) replaces the raw template copy; `soul_md` (persona
    helper) replaces the SOUL.md placeholder. Raises FileExistsError if the dir exists.
    """
    target = profiles_dir / agent_id
    target.mkdir(parents=True)
    if profile_yaml_text is None:
        shutil.copyfile(profiles_dir / "default" / "profile.yaml", target / "profile.yaml")
    else:
        (target / "profile.yaml").write_text(profile_yaml_text, encoding="utf-8")
    for name, content in _PLACEHOLDER_MD.items():
        if name == "SOUL.md" and soul_md is not None and soul_md.strip():
            (target / name).write_text(soul_md, encoding="utf-8")
        else:
            (target / name).write_text(content, encoding="utf-8")
    # v19 workspace protocol: every agent gets an (empty) memory vault + own skills dir.
    # vault/ is reserved for the v19.5 kioku provider; skills/ holds per-agent skills.
    (target / "vault").mkdir(exist_ok=True)
    (target / "skills").mkdir(exist_ok=True)
    return target


def append_registry(registry_path: Path | None, agent_id: str) -> None:
    """Append one enabled agent block (comments/entries preserved), validate-before-replace.

    The append is built IN MEMORY and only replaces the file after a clean parse that
    contains the new entry — a registry whose on-disk indent style doesn't match the
    appended block (hand-edits) raises and leaves the original byte-unchanged, instead
    of persisting a file no agent can load.
    """
    path = registry_path if registry_path is not None else _REGISTRY_PATH
    with _EDIT_LOCK:
        original = path.read_text(encoding="utf-8")
        prefix = "" if original.endswith("\n") or not original else "\n"
        new_text = original + prefix + f"  - id: {agent_id}\n    enabled: true\n"
        _replace_validated(
            path,
            new_text,
            check=lambda entries: any(e.id == agent_id and e.enabled for e in entries),
        )


def set_registry_enabled(registry_path: Path | None, agent_id: str, enabled: bool) -> None:
    """Flip one entry's `enabled:` in place (pause/resume). Comments elsewhere kept.

    Raises UnknownRegistryAgentError if the id has no entry.
    """
    path = registry_path if registry_path is not None else _REGISTRY_PATH
    with _EDIT_LOCK:
        _set_enabled_locked(path, agent_id, enabled)


def _set_enabled_locked(path: Path, agent_id: str, enabled: bool) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start, end = _entry_bounds(lines, agent_id)
    value = "true" if enabled else "false"
    for i in range(start + 1, end):
        m = re.match(r"^(\s*)enabled:\s*\S+.*$", lines[i])
        if m:
            lines[i] = f"{m.group(1)}enabled: {value}\n"
            break
    else:
        # Entry without an explicit enabled line (defaults true) — insert one.
        id_indent = re.match(r"^(\s*)-", lines[start]).group(1)  # type: ignore[union-attr]
        lines.insert(start + 1, f"{id_indent}  enabled: {value}\n")
    _replace_validated(
        path,
        "".join(lines),
        check=lambda entries: any(e.id == agent_id and e.enabled is enabled for e in entries),
    )


def remove_registry_entry(registry_path: Path | None, agent_id: str) -> None:
    """Delete one entry's block from registry.yaml. The profiles/<id>/ dir is NOT touched
    (kept as an on-disk archive — deleting an agent must never destroy its config/history).

    Raises UnknownRegistryAgentError if the id has no entry.
    """
    path = registry_path if registry_path is not None else _REGISTRY_PATH
    with _EDIT_LOCK:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start, end = _entry_bounds(lines, agent_id)
        del lines[start:end]
        _replace_validated(
            path,
            "".join(lines),
            check=lambda entries: all(e.id != agent_id for e in entries),
        )


def _entry_bounds(lines: list[str], agent_id: str) -> tuple[int, int]:
    """(start, end) line indices of the `- id: <agent_id>` block.

    The block runs from its `- id:` line up to (not including) the next `- id:` list
    item or the first line that leaves the list (a non-blank line at column 0).
    """
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*-\s+id:\s*{re.escape(agent_id)}\s*(#.*)?$", line):
            start = i
            break
    if start is None:
        raise UnknownRegistryAgentError(agent_id)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*-\s+id:", lines[j]) or re.match(r"^\S", lines[j]):
            end = j
            break
    return start, end


def _replace_validated(path: Path, new_text: str, *, check) -> None:
    """Parse `new_text` as a registry FIRST; only a clean parse + passing post-condition
    replaces the real file (atomic). Failure raises and leaves the original untouched."""
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    try:
        entries = load_registry(tmp)  # raises on malformed YAML/shape
        if not check(entries):
            raise RuntimeError("registry edit did not produce the expected entry state")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
