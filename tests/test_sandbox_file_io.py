"""v40: sandbox file I/O — upload_files/download_files back deepagents' write_file/read_file.

The bug (from the 3-harness benchmark §10.3): both backends' upload_files/download_files
were `[]` stubs, so deepagents' filesystem middleware asserted "expected N, returned 0"
whenever the deep-agent wrote a file — crashing 3/4 runs. These prove the fix: one
response per input, round-trip bytes, and path-confinement to /work (no host escape).
"""

from __future__ import annotations

import importlib.util

import pytest

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None
pytestmark = pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents not installed")


def _fake():
    from src.runtime_backends.sandbox_backend import build_sandbox_backend

    return build_sandbox_backend({"provider": "fake"})


def test_upload_returns_one_response_per_file():
    """The root-cause fix: N files in → N responses out (was 0 → assert crash)."""
    sb = _fake()
    try:
        res = sb.upload_files([("report.md", b"# hi"), ("data/notes.txt", b"x")])
        assert len(res) == 2
        assert all(r.error is None for r in res)
    finally:
        sb.teardown()


def test_upload_then_download_round_trips_bytes():
    sb = _fake()
    try:
        sb.upload_files([("out/report.md", b"noi dung bao cao")])
        got = sb.download_files(["out/report.md"])
        assert len(got) == 1
        assert got[0].content == b"noi dung bao cao" and got[0].error is None
    finally:
        sb.teardown()


def test_absolute_work_path_is_accepted():
    sb = _fake()
    try:
        r = sb.upload_files([("/work/a.txt", b"z")])
        assert r[0].error is None
        d = sb.download_files(["/work/a.txt"])
        assert d[0].content == b"z"
    finally:
        sb.teardown()


@pytest.mark.parametrize("bad", [
    "a; rm -rf /work", "x$(whoami)", "y`id`", "a|b", "a b", "a>out", "a&b", "$PATH",
])
def test_shell_metachar_paths_refused(bad):
    """The docker backend interpolates the path into `sh -c`; a metachar path must be
    refused before it can inject a command."""
    from src.runtime_backends.sandbox_backend import _confined_rel

    assert _confined_rel(bad) is None


@pytest.mark.parametrize("bad", ["/etc/passwd", "../escape.txt", "../../x", "/root/.ssh/id"])
def test_path_outside_work_refused_never_escapes(bad):
    sb = _fake()
    try:
        r = sb.upload_files([(bad, b"malicious")])
        assert r[0].error == "path_outside_work"  # refused, not written
        d = sb.download_files([bad])
        assert d[0].content is None and d[0].error == "path_outside_work"
    finally:
        sb.teardown()


def test_download_missing_file_returns_error_not_crash():
    sb = _fake()
    try:
        d = sb.download_files(["does-not-exist.md"])
        assert d[0].content is None and d[0].error == "file_not_found"
    finally:
        sb.teardown()


def test_oversized_upload_refused():
    from src.runtime_backends.sandbox_backend import _MAX_FILE_BYTES

    sb = _fake()
    try:
        r = sb.upload_files([("big.bin", b"x" * (_MAX_FILE_BYTES + 1))])
        assert r[0].error == "file_too_large"
    finally:
        sb.teardown()


def test_confined_rel_helper():
    from src.runtime_backends.sandbox_backend import _confined_rel

    assert _confined_rel("report.md") == "report.md"
    assert _confined_rel("/work/sub/x.txt") == "sub/x.txt"
    assert _confined_rel("./a/b") == "a/b"
    assert _confined_rel("/etc/passwd") is None
    assert _confined_rel("../x") is None
    assert _confined_rel("a/../../x") is None


def _docker_available() -> bool:
    import shutil
    import subprocess

    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_real_docker_round_trip_and_confine():
    """The bug was Docker-specific: /work is a tmpfs over a READ-ONLY rootfs, so
    put_archive/get_archive fail — we write/read via exec+base64. This proves the real
    container path (upload→download binary round-trip + /etc refused)."""
    from src.runtime_backends.sandbox_backend import build_sandbox_backend

    sb = build_sandbox_backend({"provider": "docker", "network": False})
    try:
        payload = b"# report\nbinary: \x00\x01\xff"
        up = sb.upload_files([("out/report.md", payload)])
        assert up[0].error is None
        down = sb.download_files(["out/report.md"])
        assert down[0].content == payload and down[0].error is None
        assert sb.upload_files([("/etc/evil", b"x")])[0].error == "path_outside_work"
        assert sb.download_files(["/etc/passwd"])[0].error == "path_outside_work"
    finally:
        sb.teardown()
