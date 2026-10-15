# [desc] BUG 2 : intégration d'un worktree quand la base 'develop' a AVANCÉ ou n'est pas
# checkout dans l'arbre principal. Vrai git sur repo temp, zéro agent LLM. Prouve qu'un
# merge non-FF réussit et que needs_attention ne survient que sur cas réellement bloquant. [/desc]
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import worktrees
from tests.git_modeles import develop_un_commit


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _commit(cwd, msg):
    _git(cwd, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", msg)


@pytest.fixture
def repo(tmp_path, depot_modele) -> Path:
    """Repo git avec une branche develop et un commit initial : le repo principal."""
    return depot_modele(tmp_path / "primary", develop_un_commit)


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

def test_integrates_when_develop_advanced_primary_on_base(tmp_path, repo):
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

def test_integrates_when_primary_on_other_branch(tmp_path, repo):
    _git(repo, "branch", "main")
    _git(repo, "checkout", "-q", "main")          # l'humain bosse ailleurs
    meta = _provision(repo, tmp_path, "t2", "wt2")
    _agent_work(meta, "W\n")

    result = worktrees.integrate(meta)

    assert result == {"ok": True, "state": "integrated"}
    assert "agent work" in _log(repo, "develop")   # develop a bien avancé
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"  # HEAD intact


# ── conflit réel de synchro → conflict (worktree laissé pour résolution) ───────────

def test_real_conflict_reports_conflict_not_integrated(tmp_path, repo):
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

def test_dirty_base_still_merges_via_stash_without_losing_work(tmp_path, repo):
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

def test_restore_conflict_keeps_main_tree_clean_and_stashes_wip(tmp_path, repo):
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


def test_preexisting_conflict_residue_blocks_integration(tmp_path, repo):
    meta = _provision(repo, tmp_path, "t6", "wt6")
    _agent_work(meta, "W\n")
    # Résidu de conflit préexistant dans l'arbre principal (marqueurs laissés par un incident passé).
    (repo / "f.txt").write_text("A\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> other\n", encoding="utf-8")
    _git(repo, "add", "-A")   # staged mais non résolu → le garde-fou doit refuser via marqueurs

    result = worktrees.integrate(meta)

    assert result["ok"] is False
    assert result["state"] == "needs_attention"
    assert "résidu de conflit" in result["error"]


# ── deux AGENTS (deux process) intègrent en même temps dans la même base ─────────────

_INTEGRER_DANS_UN_PROCESS = """
import json, os, sys, time
from bouzecode.web_v2.services.work import worktrees
#  Élargit la fenêtre entre la synchro de la base et le contrôle « la base n'a pas bougé » :
#  sans verrou entre process, le frère intègre pendant ce temps-là.
_orig = worktrees._conflict_marker_files
worktrees._conflict_marker_files = lambda repo, ref: (time.sleep(1.0), _orig(repo, ref))[1]
meta, go = json.loads(sys.argv[1]), sys.argv[2]
while not os.path.exists(go):
    time.sleep(0.01)
print(json.dumps(worktrees.integrate(meta)))
"""


def test_deux_freres_integrent_en_meme_temps_depuis_leurs_process(tmp_path, repo):
    """`Environment(action='integrate')` intègre depuis le process de l'AGENT : le verrou par
    thread du serveur ne sérialisait rien entre deux frères. Lancés ensemble (lot d'`Agent`),
    ils finissent ensemble ; le second échouait : « 'develop' a avancé pendant l'intégration »
    (vu dans le bac à sable, scénario `manager-worktree`) ou, merges simultanés dans l'arbre
    principal, « Impossible de créer '…/index.lock' » (ce test). Les deux doivent être intégrés."""
    import json
    import os
    import sys

    metas = [_provision(repo, tmp_path, f"f{i}", f"wtf{i}") for i in (1, 2)]
    for i, meta in enumerate(metas, 1):
        _agent_work(meta, f"frere {i}\n", filename=f"frere{i}.txt")
    go = tmp_path / "go"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    procs = [subprocess.Popen([sys.executable, "-c", _INTEGRER_DANS_UN_PROCESS, json.dumps(m),
                               str(go)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=env) for m in metas]
    go.write_text("go", encoding="utf-8")
    sorties = [p.communicate(timeout=120) for p in procs]

    resultats = [json.loads(out.strip().splitlines()[-1]) for out, _err in sorties]
    assert all(r.get("ok") for r in resultats), (resultats, [err[-800:] for _o, err in sorties])
    fichiers = _git(repo, "ls-tree", "--name-only", "develop").stdout.split()
    assert {"frere1.txt", "frere2.txt"} <= set(fichiers)
