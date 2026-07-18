"""CLI adapter — run `gh` (GitHub CLI) and return parsed JSON.

GitHub integration is via the `gh` CLI (not an MCP server). This adapter is the
mechanism only: it runs a fixed argv built by the `tools/github_read.py` layer.
It deliberately does NOT accept arbitrary LLM-provided commands — the LLM never
reaches this surface; only typed read helpers call it with known args.

Bounded: a timeout so a hung CLI cannot stall the agent. Errors are explicit
(missing `gh`, non-zero exit, unparseable JSON) and never swallowed.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

_GH_TIMEOUT_S = 30.0


def run_gh(args: list[str], *, timeout: float = _GH_TIMEOUT_S) -> Any:
    """Run `gh <args>` and return parsed JSON (list or dict).

    `args` must include `--json <fields>` for JSON output. Raises a clear error
    if `gh` is missing, exits non-zero, or returns non-JSON.
    """
    cmd = ["gh", *args]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "`gh` (GitHub CLI) is not installed or not on PATH. "
            "Install it and run `gh auth login`."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"`gh {' '.join(args)}` timed out after {timeout:.0f}s.") from exc

    if completed.returncode != 0:
        # stderr may carry auth hints; do not include token values (gh doesn't echo them).
        raise RuntimeError(
            f"`gh {' '.join(args)}` failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()}"
        )

    out = completed.stdout.strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"`gh {' '.join(args)}` returned non-JSON output (did you pass --json?)."
        ) from exc
