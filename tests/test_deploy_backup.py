"""v6 M16: deploy scripts — backup excludes .env (R4), restore refuses a leaky archive.

Runs the real shell scripts in a temp repo layout (subprocess) so the exclusion is proven
against the actual tar invocation, not a reimplementation.
"""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BACKUP = _REPO / "deploy" / "backup.sh"
_RESTORE = _REPO / "deploy" / "restore.sh"


def _fake_repo(tmp_path: Path) -> Path:
    """A minimal repo layout with a secret-bearing .env that must NEVER be backed up."""
    (tmp_path / ".data" / "agents" / "x").mkdir(parents=True)
    (tmp_path / ".data" / "agents" / "x" / "audit.jsonl").write_text("event\n")
    (tmp_path / "profiles" / "x").mkdir(parents=True)
    (tmp_path / "profiles" / "x" / "profile.yaml").write_text("id: x\n")
    (tmp_path / "registry.yaml").write_text("agents: []\n")
    (tmp_path / ".env").write_text("SLACK_XOXC_TOKEN=xoxc-super-secret-leak\n")
    # symlink deploy/ so backup.sh resolves REPO_DIR to tmp_path
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "backup.sh").symlink_to(_BACKUP)
    (tmp_path / "deploy" / "restore.sh").symlink_to(_RESTORE)
    return tmp_path


def test_backup_excludes_env_and_secret(tmp_path):
    repo = _fake_repo(tmp_path)
    dest = tmp_path / "backups"
    subprocess.run(["bash", str(repo / "deploy" / "backup.sh"), str(dest)],
                   cwd=repo, check=True, capture_output=True)
    archives = list(dest.glob("mpm-backup-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as tf:
        names = tf.getnames()
        # .env must not be in the archive at any level
        assert not any(n.endswith(".env") for n in names), names
        # the token must not appear in any member's content
        for member in tf.getmembers():
            if member.isfile():
                data = tf.extractfile(member).read()
                assert b"xoxc-super-secret-leak" not in data
        # the real state IS there
        assert any("registry.yaml" in n for n in names)
        assert any("audit.jsonl" in n for n in names)


def test_restore_refuses_archive_containing_env(tmp_path):
    """A tampered archive that DOES contain a .env is rejected (defense in depth)."""
    repo = _fake_repo(tmp_path)
    leaky = tmp_path / "leaky.tar.gz"
    with tarfile.open(leaky, "w:gz") as tf:
        env = tmp_path / ".env"
        tf.add(env, arcname=".env")
    result = subprocess.run(["bash", str(repo / "deploy" / "restore.sh"), str(leaky)],
                            cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert "refusing to restore" in result.stdout.lower() or "refusing" in result.stderr.lower()


def test_backup_restore_roundtrip(tmp_path):
    repo = _fake_repo(tmp_path)
    dest = tmp_path / "backups"
    subprocess.run(["bash", str(repo / "deploy" / "backup.sh"), str(dest)],
                   cwd=repo, check=True, capture_output=True)
    archive = next(dest.glob("mpm-backup-*.tar.gz"))
    # wipe state (keep .env), restore, assert state came back
    (repo / "registry.yaml").unlink()
    subprocess.run(["bash", str(repo / "deploy" / "restore.sh"), str(archive)],
                   cwd=repo, check=True, capture_output=True)
    assert (repo / "registry.yaml").read_text() == "agents: []\n"
    assert (repo / ".env").read_text() == "SLACK_XOXC_TOKEN=xoxc-super-secret-leak\n"  # untouched


def test_web_hash_password_cli_roundtrips():
    """`mpm web` exposes hash-password; the hash verifies against the plaintext."""
    from my_crew.server.auth import _verify, hash_password

    h = hash_password("prod-pass")
    assert _verify("prod-pass", h) and not _verify("nope", h)
