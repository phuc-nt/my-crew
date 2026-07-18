"""Read + save profile files for the config-edit dashboard surface (v2 M2-P7 Slice 3).

profile.yaml is saved with VALIDATE-then-atomic-replace: the new text is validated by
running the SAME builders `load_profile` uses (which RAISE on bad config, incl. the
stakeholder-channel cross-validation) IN MEMORY — no file is touched until a clean
build — then `os.replace`d over the real file (atomic). A bad edit raises and leaves the
original byte-unchanged.

SOUL.md / PROJECT.md are free-text (atomic write, no validation). MEMORY.md is NOT
writable here (the agent self-writes it via the P8 remember node); `save_markdown`
whitelists soul/project only.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from my_crew.profile.loader import _PROFILES_DIR
from my_crew.runtime.agent_paths import _validate_agent_id, agent_data_dir

_EDITABLE_MD = {"SOUL.md", "PROJECT.md"}  # MEMORY.md is agent-written, read-only here


def _profile_dir(agent_id: str) -> Path:
    return _PROFILES_DIR / _validate_agent_id(agent_id)


def read_profile_files(agent_id: str) -> dict[str, str]:
    """Return the 4 profile files' text (missing → empty string)."""
    d = _profile_dir(agent_id)
    return {name.split(".")[0].lower(): _read(d / name)
            for name in ("profile.yaml", "SOUL.md", "PROJECT.md", "MEMORY.md")}


def save_profile_yaml(agent_id: str, new_text: str) -> None:
    """Validate the new profile.yaml in memory, then atomically replace the real file.

    Raises ValueError (not a YAML mapping) / RuntimeError (bad config, e.g. the
    stakeholder-channel rule) WITHOUT touching the file. On a clean build, atomically
    replaces profiles/<id>/profile.yaml.
    """
    from my_crew.config.config_builders import (
        build_reporting_config_from_dict,
        build_settings_from_dict,
    )
    from my_crew.profile.loader_mapping import build_reporting_dict, build_settings_dict

    doc = yaml.safe_load(new_text)
    if not isinstance(doc, dict):
        raise ValueError("profile.yaml must be a YAML mapping (key: value), not a list/scalar.")
    # Run the real builders — they raise on bad config. Nothing is written yet.
    build_settings_from_dict(build_settings_dict(doc, agent_data_dir(agent_id)))
    config = build_reporting_config_from_dict(build_reporting_dict(doc))
    # v3 M11: the inbox block is parsed by load_profile — validate it here too so a bad
    # edit 400s in the editor instead of crashing the next scheduled load.
    from my_crew.profile.loader import _parse_inbox

    _parse_inbox(doc.get("inbox"), config)
    _atomic_write(_profile_dir(agent_id) / "profile.yaml", new_text)


def save_markdown(agent_id: str, filename: str, new_text: str) -> None:
    """Save SOUL.md / PROJECT.md (free text, atomic). Rejects any other name (esp. MEMORY.md)."""
    if filename not in _EDITABLE_MD:
        raise ValueError(f"{filename} is not editable here (only SOUL.md / PROJECT.md).")
    _atomic_write(_profile_dir(agent_id) / filename, new_text)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
