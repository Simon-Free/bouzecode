# [desc] Régression : _safe_cwd rabat un worktree MORT (dossier subsistant, .git disparu) au lieu de
# revivre l'agent dans un dossier vide (« worktree vide » → blocage awaiting_input). [/desc]
"""Un merge+reap peut laisser le DOSSIER worktree sur disque (readme_sync repeint même un
AGENTS.md solitaire) alors que le `.git` et le code ont disparu. `os.path.isdir` ne distingue
pas ce cadavre d'un checkout vivant : `resume_agent`/`_respawn` faisaient donc Popen dedans et
l'agent renaissait sans source. Le backstop rabat sur le cwd serveur (checkout vivant) — pour
TOUT chemin de reprise, y compris un sous-agent manager SANS ticket que rehome ne peut pas
re-provisionner.
"""
import bouzecode.web_v2.runtime.runner as runner


def _worktree(tmp_path, alive: bool):
    # Reproduit l'arborescence ~/.bouzecode/worktrees/<repo>/<id> exigée par le marqueur.
    wt = tmp_path / ".bouzecode" / "worktrees" / "repo" / "deadbeef"
    wt.mkdir(parents=True)
    (wt / "AGENTS.md").write_text("solitaire repeint par readme_sync", encoding="utf-8")
    if alive:
        (wt / ".git").write_text("gitdir: ...", encoding="utf-8")
    return wt


def test_dead_worktree_floored_to_none(tmp_path):
    dead = _worktree(tmp_path, alive=False)
    assert runner._is_dead_worktree(str(dead)) is True
    assert runner._safe_cwd(str(dead)) is None


def test_live_worktree_kept(tmp_path):
    live = _worktree(tmp_path, alive=True)
    assert runner._is_dead_worktree(str(live)) is False
    assert runner._safe_cwd(str(live)) == str(live)


def test_non_worktree_dir_without_git_kept(tmp_path):
    # Un projet NON-git (hors ~/.bouzecode/worktrees) tourne dans son propre dossier : jamais rabattu.
    proj = tmp_path / "some_project"
    proj.mkdir()
    assert runner._is_dead_worktree(str(proj)) is False
    assert runner._safe_cwd(str(proj)) == str(proj)


def test_vanished_dir_floored_to_none(tmp_path):
    assert runner._safe_cwd(str(tmp_path / "gone")) is None
