# [desc] BUG 2 : intégration d'un worktree quand la base 'develop' a AVANCÉ ou n'est pas
# checkout dans l'arbre principal. Vrai git sur repo temp, zéro agent LLM. Prouve qu'un
# merge non-FF réussit et que needs_attention ne survient que sur cas réellement bloquant. [/desc]
from __future__ import annotations

import subprocess
from pathlib import Path

from bouzecode.web_v2.services.work import worktrees


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _commit(cwd, msg):
    _git(cwd, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", msg)


def _make_repo(root: Path) -> Path:
    """Repo git avec une branche develop et un commit initial. Renvoie le repo principal."""
    repo = root / "primary"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "develop")
    (repo / "f.txt").write_text("A\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _commit(repo, "A")
    return repo


def _provision(repo: Path, root: Path, ticket_id: str, worktree_name: str) -> dict:
    """Crée un worktree agent/<id> depuis develop et renvoie le meta que consomme integrate()."""
    wt = root / worktree_name
    branch = f"agent/{ticket_id}"
    res = _git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "develop")
    assert res.returncode == 0, res.stderr
    return {"repo_root": str(repo), "worktree": str(wt), "base": "develop", "branch": branch}


def _agent_work(meta: dict, content: str, filename: str = "f.txt"):
    wt = Path(meta["worktree"])
    path = wt / filename
    path.write_text((path.read_text(encoding="utf-8") if path.exists() else "") + content,
                    encoding="utf-8")
    _git(wt, "add", "-A")
    _commit(wt, "agent work")


def _log(repo, ref="develop"):
    return _git(repo, "log", "--oneline", ref).stdout


# ── develop a AVANCÉ pendant que le worktree travaillait (primary sur develop) ─────

def test_integrates_when_develop_advanced_primary_on_base(tmp_path):
    repo = _make_repo(tmp_path)
    meta = _provision(repo, tmp_path, "t1", "wt1")
    _agent_work(meta, "W\n")                       # commit dans le worktree
    (repo / "g.txt").write_text("B\n", encoding="utf-8")  # develop avance (autre merge)
    _git(repo, "add", "-A")
    _commit(repo, "B")

    result = worktrees.integrate(meta)

    assert result == {"ok": True, "state": "integrated"}
    log = _log(repo)
    assert "agent work" in log and "B" in log  # les deux travaux sont sur develop


# ── l'arbre principal est checkout sur une AUTRE branche que la base ───────────────

def test_integrates_when_primary_on_other_branch(tmp_path):
    repo = _make_repo(tmp_path)
    _git(repo, "branch", "main")
    _git(repo, "checkout", "-q", "main")          # l'humain bosse ailleurs
    meta = _provision(repo, tmp_path, "t2", "wt2")
    _agent_work(meta, "W\n")

    result = worktrees.integrate(meta)

    assert result == {"ok": True, "state": "integrated"}
    assert "agent work" in _log(repo, "develop")   # develop a bien avancé
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"  # HEAD intact


# ── conflit réel de synchro → conflict (worktree laissé pour résolution) ───────────

def test_real_conflict_reports_conflict_not_integrated(tmp_path):
    repo = _make_repo(tmp_path)
    meta = _provision(repo, tmp_path, "t3", "wt3")
    _agent_work(meta, "agent-line\n")                       # modifie f.txt côté agent
    (repo / "f.txt").write_text("A\ndevelop-line\n", encoding="utf-8")  # develop modifie la MÊME zone
    _git(repo, "add", "-A")
    _commit(repo, "develop change")

    result = worktrees.integrate(meta)

    assert result["ok"] is False
    assert result["state"] == "conflict"
    assert "f.txt" in result["files"]
    assert "agent work" not in _log(repo, "develop")        # rien mergé sur develop


# ── base checkout AVEC arbre principal SALE → 2bcf44c : ne BLOQUE plus (stash → merge →
#    restaure). Le merge n'est plus otage d'un artefact non commité laissé par la flotte. ─

def test_dirty_base_still_merges_via_stash_without_losing_work(tmp_path):
    repo = _make_repo(tmp_path)
    meta = _provision(repo, tmp_path, "t4", "wt4")
    _agent_work(meta, "W\n")                                            # commit agent sur f.txt
    (repo / "f.txt").write_text("A\nuncommitted local edit\n", encoding="utf-8")  # arbre sale (même fichier)

    result = worktrees.integrate(meta)

    # Le travail VALIDÉ atterrit malgré la base sale (fin de « les merges ne se déclenchent pas »).
    assert result["ok"] is True
    assert result["state"] == "integrated"
    assert "agent work" in _log(repo, "develop")
    # Invariant : le sale local n'est JAMAIS perdu — restauré dans l'arbre, ou sauf dans la pile stash
    # (ici le sale touchait le même fichier → le stash pop conflicte → conservé dans `git stash`).
    working = (repo / "f.txt").read_text(encoding="utf-8")
    stash = _git(repo, "stash", "list").stdout
    assert ("uncommitted local edit" in working) or ("bouzecode-auto-integrate" in stash)


# ── 2bcf44c durci : le pop de restore du WIP humain conflicte APRÈS un merge réussi.
#    Avant : l'arbre principal restait en UU + marqueurs `<<<<<<<` (page morte). Désormais :
#    reset --hard HEAD (arbre = état mergé propre), WIP re-stashé, restore_conflict exposé. ─

def test_restore_conflict_keeps_main_tree_clean_and_stashes_wip(tmp_path):
    repo = _make_repo(tmp_path)
    meta = _provision(repo, tmp_path, "t5", "wt5")
    _agent_work(meta, "W\n")                                             # commit agent sur f.txt
    (repo / "f.txt").write_text("A\nuncommitted local edit\n", encoding="utf-8")  # WIP humain, même fichier

    result = worktrees.integrate(meta)

    # Le merge EST livré malgré le pop de restore conflictuel.
    assert result["ok"] is True
    assert result["state"] == "integrated"
    assert "agent work" in _log(repo, "develop")
    # L'arbre principal est PROPRE : aucun fichier en UU ni marqueur `<<<<<<<`.
    assert worktrees._conflict_residue(str(repo)) == []
    working = (repo / "f.txt").read_text(encoding="utf-8")
    assert "<<<<<<<" not in working
    # Le WIP humain rejeté n'est PAS perdu : il reste dans un stash nommé.
    stash = _git(repo, "stash", "list").stdout
    assert "bouzecode-auto-integrate" in stash
    # Le résultat expose le conflit de restore + la ref du stash pour l'UI.
    rc = result["restore_conflict"]
    assert rc["branch"] == meta["branch"]
    assert rc["stash_ref"].startswith("stash@{")
    assert "f.txt" in rc["files"]


def test_preexisting_conflict_residue_blocks_integration(tmp_path):
    repo = _make_repo(tmp_path)
    meta = _provision(repo, tmp_path, "t6", "wt6")
    _agent_work(meta, "W\n")
    # Résidu de conflit préexistant dans l'arbre principal (marqueurs laissés par un incident passé).
    (repo / "f.txt").write_text("A\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> other\n", encoding="utf-8")
    _git(repo, "add", "-A")   # staged mais non résolu → le garde-fou doit refuser via marqueurs

    result = worktrees.integrate(meta)

    assert result["ok"] is False
    assert result["state"] == "needs_attention"
    assert "résidu de conflit" in result["error"]
