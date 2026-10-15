"""Tour 1 en worktree → integrate + cleanup → tour 2 du MÊME process (TUI / pool chaud) :
l'agent doit se retrouver dans un worktree neuf sans appeler Environment(action='worktree')."""
import os
import subprocess

from bouzecode.backend.tools import environment
from bouzecode.web_v2.services.work import worktrees


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def test_tour_suivant_reisole_apres_integration(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "c1")
    wt = tmp_path / "wt1"
    _git(repo, "worktree", "add", "-b", "agent/a1", str(wt))
    (wt / "g.txt").write_text("travail du tour 1")
    _git(wt, "add", "g.txt")
    _git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "tour1")

    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.delenv("BOUZECODE_TICKET_SLUG", raising=False)
    monkeypatch.delenv("BOUZECODE_TICKET_ID", raising=False)
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", str(wt))
    monkeypatch.chdir(wt)
    monkeypatch.setattr(environment, "_A_REISOLER", {})
    monkeypatch.setattr(environment, "_PENDING_CLEANUP", {})
    config = {"_web_agent_dir": str(tmp_path / "ipc" / "a1")}

    # Tour 1 : intégration puis rangement, comme le demande le profil.
    sortie = environment._environment({"action": "integrate"}, config)
    assert "Merge propre" in sortie, sortie
    environment._environment({"action": "cleanup"}, config)
    assert _same(os.getcwd(), repo)  # le process est revenu dans le dépôt partagé

    # Tour 2, même process : la ré-isolation se fait sans geste de l'agent.
    message = environment.reisoler_avant_tour(config)
    assert message, "aucune ré-isolation au tour suivant : l'agent écrirait dans le dépôt partagé"
    nouveau = os.getcwd()
    assert not _same(nouveau, repo)
    assert os.path.isfile(os.path.join(nouveau, ".git"))  # un vrai worktree git
    assert os.path.isfile(os.path.join(nouveau, "g.txt"))  # il voit le travail mergé
    assert _same(environment.variable("BOUZECODE_WORKTREE_ROOT"), nouveau)

    # Le drapeau est consommé : le tour 3 ne recrée rien.
    assert environment.reisoler_avant_tour(config) == ""


def test_pas_de_reisolation_sans_integration(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "_A_REISOLER", {})
    assert environment.reisoler_avant_tour({}) == ""
