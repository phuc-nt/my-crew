"""Installed distribution version, one place — `/health`, `mpm --version` and the web
"bản mới đã cài" banner must all report the same string, or the banner would nag after
an install that `mpm --version` says did nothing."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

UNINSTALLED = "0.0.0+uninstalled"


def dist_version() -> str:
    """The installed `my-crew` version; a bare checkout without an install has none."""
    try:
        return version("my-crew")
    except PackageNotFoundError:
        return UNINSTALLED
