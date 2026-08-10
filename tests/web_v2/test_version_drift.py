# [desc] Tests version_state: drift quand HEAD avance ET quand le source du disque bouge sans commit, gardes SHA/empreinte vides, fail-safe git absent, cache TTL de l'etat servi par /api/version. [/desc]
import os
import subprocess
from pathlib import Path

from bouzecode.web_v2 import version as _version


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
    ).strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a real git repo with one commit; return (repo_path, head_sha)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("one", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c1")
    head = _git(repo, "rev-parse", "HEAD")
    return repo, head


def test_no_drift_at_boot_sha(tmp_path):
    repo, head = _make_repo(tmp_path)
    state = _version.version_state(head, "1.2.3", str(repo))
    assert state["boot_sha"] == head
    assert state["current_head_sha"] == head
    assert state["drift"] is False
    assert state["boot_version"] == "1.2.3"


def test_drift_when_head_advances(tmp_path):
    repo, boot = _make_repo(tmp_path)
    (repo / "a.txt").write_text("two", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c2")
    new_head = _git(repo, "rev-parse", "HEAD")
    assert new_head != boot

    state = _version.version_state(boot, "1.2.3", str(repo))
    assert state["boot_sha"] == boot
    assert state["current_head_sha"] == new_head
    assert state["drift"] is True


def test_drift_when_source_changed_without_any_commit(tmp_path):
    """LE bug du 27/07 : le code du disque a change, HEAD non -> il faut quand meme
    avertir. Un serveur booté le 22/07 servait des pages mortes (nav « Projets » -> 500)
    sans le moindre bandeau, parce que la derive n'etait que dans le working tree."""
    repo, head = _make_repo(tmp_path)
    source = repo / "src"
    source.mkdir()
    (source / "mod.py").write_text("v1", encoding="utf-8")
    boot_fingerprint = _version.source_fingerprint(str(source))

    (source / "mod.py").write_text("v2 — edite apres le boot", encoding="utf-8")
    os.utime(source / "mod.py", (2_000_000_000, 2_000_000_000))

    state = _version.version_state(head, "1.2.3", str(repo), boot_fingerprint, str(source))
    assert state["current_head_sha"] == head  # aucun commit n'a bouge
    assert state["sha_drift"] is False
    assert state["source_drift"] is True
    assert state["drift"] is True


def test_drift_when_a_source_file_is_deleted(tmp_path):
    """Une page supprimee du disque (le cas /projects) compte aussi comme derive."""
    repo, head = _make_repo(tmp_path)
    source = repo / "src"
    source.mkdir()
    (source / "keep.py").write_text("k", encoding="utf-8")
    (source / "gone.py").write_text("g", encoding="utf-8")
    boot_fingerprint = _version.source_fingerprint(str(source))

    (source / "gone.py").unlink()

    state = _version.version_state(head, "1.2.3", str(repo), boot_fingerprint, str(source))
    assert state["source_drift"] is True


def test_no_source_drift_when_nothing_moved(tmp_path):
    repo, head = _make_repo(tmp_path)
    source = repo / "src"
    source.mkdir()
    (source / "mod.py").write_text("v1", encoding="utf-8")
    boot_fingerprint = _version.source_fingerprint(str(source))

    state = _version.version_state(head, "1.2.3", str(repo), boot_fingerprint, str(source))
    assert state["source_drift"] is False
    assert state["drift"] is False


def test_no_source_drift_when_fingerprint_unknown(tmp_path):
    """Empreinte de boot vide (racine illisible) -> jamais de bandeau faux."""
    repo, head = _make_repo(tmp_path)

    state = _version.version_state(head, "1.2.3", str(repo), "", str(repo))
    assert state["source_drift"] is False
    assert state["drift"] is False


def test_no_drift_when_boot_sha_empty(tmp_path):
    repo, _ = _make_repo(tmp_path)
    # Guard: an unknown/empty boot SHA must never trip the drift banner.
    state = _version.version_state("", "unknown", str(repo))
    assert state["drift"] is False


def test_fail_safe_when_git_absent(tmp_path, monkeypatch):
    # Constraint "ne pas casser le boot": if git is missing from PATH,
    # subprocess.run raises FileNotFoundError. version_state / capture_boot_state
    # must swallow it, yield an empty current head and NEVER trip the banner.
    repo, head = _make_repo(tmp_path)

    def _boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(_version.subprocess, "run", _boom)
    state = _version.version_state(head, "1.2.3", str(repo))
    assert state["current_head_sha"] == ""
    assert state["drift"] is False
    assert state["boot_sha"] == head

    # capture_boot_state must not raise either (called at boot before routes).
    monkeypatch.setattr(_version, "BOOT_SHA", "")
    monkeypatch.setattr(_version, "REPO_ROOT", "")
    _version.capture_boot_state()  # no exception = boot survives git-less env
