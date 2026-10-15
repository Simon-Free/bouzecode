"""After a successful integration, develop is always pushed to origin (user rule)."""
import subprocess

from bouzecode.backend.tools.environment import _pousser_base


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo_with_remote(tmp_path, branch):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", branch, str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "c1")
    _git(repo, "remote", "add", "origin", str(remote))
    return repo, remote


def test_develop_is_pushed_to_origin(tmp_path):
    repo, remote = _repo_with_remote(tmp_path, "develop")
    msg = _pousser_base(str(repo), "develop")
    assert "poussé" in msg
    assert _git(remote, "rev-parse", "develop") == _git(repo, "rev-parse", "HEAD")


def test_base_guessed_from_current_branch(tmp_path):
    repo, remote = _repo_with_remote(tmp_path, "develop")
    _pousser_base(str(repo), "")
    assert _git(remote, "rev-parse", "develop") == _git(repo, "rev-parse", "HEAD")


def test_other_branch_is_not_pushed(tmp_path):
    repo, remote = _repo_with_remote(tmp_path, "main")
    assert _pousser_base(str(repo), "main") == ""
    assert _git(remote, "branch") == ""


def test_push_failure_is_reported_not_raised(tmp_path):
    repo, _ = _repo_with_remote(tmp_path, "develop")
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    msg = _pousser_base(str(repo), "develop")
    assert "ÉCHOUÉ" in msg
