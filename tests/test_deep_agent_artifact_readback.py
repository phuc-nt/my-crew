"""v41 P2: deep_agent reads back /work/*.md artifacts before teardown.

The agent often writes its report to a file rather than the reply text; teardown then
removes the container and the report is lost. `_merge_sandbox_artifacts` reads the .md
files back and appends any content not already in the reply — best-effort, never failing
the run.
"""

from __future__ import annotations

import importlib.util

import pytest

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None
pytestmark = pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents not installed")


class _Resp:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error


class _FakeBackend:
    """Records /work/*.md and serves ls + download like the real backend."""

    def __init__(self, files: dict[str, bytes]):
        self._files = files  # name → bytes

    def execute(self, cmd):
        class _R:
            output = "\n".join(f"/work/{n}" for n in self._files) if "ls" in cmd else ""
        _R._files = self._files
        return _R()

    def download_files(self, paths):
        out = []
        for p in paths:
            name = p.rsplit("/", 1)[-1]
            data = self._files.get(name)
            out.append(_Resp(content=data, error=None if data is not None else "file_not_found"))
        return out


def _merge(backend, text):
    from src.runtime_backends.deep_agent_loop import _merge_sandbox_artifacts

    return _merge_sandbox_artifacts(backend, text)


def test_artifact_appended_when_not_in_reply():
    be = _FakeBackend({"report.md": b"# Bao cao\nNoi dung day du cua bao cao deep agent"})
    out = _merge(be, "tom tat ngan")
    assert "### Artifact: /work/report.md" in out
    assert "Noi dung day du" in out


def test_artifact_skipped_when_already_in_reply():
    body = b"# Bao cao chi tiet ABC"
    be = _FakeBackend({"report.md": body})
    out = _merge(be, "# Bao cao chi tiet ABC — da nam trong reply")
    assert "### Artifact" not in out  # not duplicated


def test_no_md_files_returns_text_unchanged():
    be = _FakeBackend({})
    assert _merge(be, "reply text") == "reply text"


def test_download_error_is_skipped_not_fatal():
    class _Broken(_FakeBackend):
        def download_files(self, paths):
            return [_Resp(content=None, error="file_not_found")]

    be = _Broken({"report.md": b"x"})
    assert _merge(be, "reply") == "reply"  # skipped, run not broken


def test_binary_non_utf8_artifact_skipped():
    be = _FakeBackend({"report.md": b"\xff\xfe\x00binary"})
    assert _merge(be, "reply") == "reply"  # undecodable → skipped


def test_execute_failure_leaves_text_unchanged():
    class _Boom(_FakeBackend):
        def execute(self, cmd):
            raise RuntimeError("docker gone")

    assert _merge(_Boom({"r.md": b"x"}), "reply") == "reply"  # best-effort


def test_total_size_capped():
    from src.runtime_backends.deep_agent_loop import _ARTIFACT_MERGE_MAX_CHARS

    big = b"y" * (_ARTIFACT_MERGE_MAX_CHARS + 5000)
    be = _FakeBackend({"big.md": big})
    out = _merge(be, "reply")
    assert len(out) <= _ARTIFACT_MERGE_MAX_CHARS
