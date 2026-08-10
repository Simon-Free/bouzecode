# [desc] Relancer un ticket ne doit JAMAIS faire disparaître un commit de sa branche. [/desc]
"""Cas vécu du 28/07 : `POST /api/tickets/<slug>/<id>/launch` avec un corps VIDE hérite de
l'isolation inscrite sur le ticket (`worktree`), donc passe par `dispatch.reisolate` →
`worktrees.discard_stale` → `git branch -D agent/<id>`. Les commits que la branche portait
partaient avec elle, sans un mot :

    agent/cafed00d@{0}: branch: Created from develop
    agent/d0d0face@{0}: branch: Created from develop

(le second effaçait une sauvegarde manuelle, `bd63566`, récupérée in extremis par un tag).
Quatre tickets relancés dans la même minute ont perdu ainsi leur livraison ; les deux qui
ont survécu n'étaient pas passés par cette route.

Aucun mock : vrai dépôt git, vrais worktrees, vrai store SQLite (isolé par le conftest)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import dispatch, tickets, worktrees

SLUG = "proj-relance"


def git(cwd, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    assert res.returncode == 0, f"git {' '.join(args)} → {res.stderr}"
    return res.stdout.strip()


def commit_exists(repo, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def commit_reachable(repo, sha: str) -> bool:
    """Le commit est-il tenu par une ref (branche/tag) ? Un objet seulement « existant »
    est un orphelin en sursis : le prochain `git gc` l'efface. C'est le VRAI critère."""
    refs = git(repo, "for-each-ref", "--format=%(refname)")
    return any(subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, ref],
                              capture_output=True).returncode == 0
               for ref in refs.splitlines() if ref)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Dépôt avec `develop` checkout, comme le dépôt principal servi par le serveur."""
    root = tmp_path / "projet"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t.t")
    git(root, "config", "user.name", "t")
    (root / "README.md").write_text("init\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    git(root, "branch", "-M", "develop")
    return root


@pytest.fixture()
def ticket_isole(repo):
    """Un ticket `worktree` déjà provisionné, tel qu'un premier run l'a laissé."""

    def _make(livraison: str = "") -> dict:
        ticket = tickets.create_ticket(SLUG, "ticket à relancer", "refais-le")
        meta = worktrees.provision(str(repo), ticket["id"], base_branch="develop",
                                   with_venv=False)
        assert meta["ok"], meta
        ticket["isolation"] = "worktree"
        ticket["worktree"] = meta
        tickets.update_ticket(SLUG, ticket)
        if livraison:
            (Path(meta["worktree"]) / "livraison.py").write_text(livraison, encoding="utf-8")
            git(meta["worktree"], "add", "-A")
            git(meta["worktree"], "commit", "-q", "-m", "agent: travail livré")
        return tickets.get_ticket(SLUG, ticket["id"])

    return _make


def test_le_commit_de_la_branche_survit_a_la_relance(repo, ticket_isole):
    """LE bug : après relance, le commit livré doit encore être tenu par une ref."""
    ticket = ticket_isole(livraison="x = 1\n")
    livre = git(ticket["worktree"]["worktree"], "rev-parse", "HEAD")

    dispatch.reisolate(SLUG, ticket, str(repo))

    assert commit_exists(repo, livre), "le commit livré a été détruit par la relance"
    assert commit_reachable(repo, livre), "le commit livré n'est plus tenu par aucune ref"


def test_la_relance_repart_du_travail_deja_commite(repo, ticket_isole):
    """Le nouvel agent retrouve le travail de son prédécesseur dans son worktree."""
    ticket = ticket_isole(livraison="x = 1\n")

    cwd = dispatch.reisolate(SLUG, ticket, str(repo))

    assert (Path(cwd) / "livraison.py").read_text(encoding="utf-8") == "x = 1\n"


def test_une_branche_sans_travail_est_re_provisionnee(repo, ticket_isole):
    """Non-régression `discard_stale` : sans commit à sauver, la relance repart bien
    d'un worktree neuf sur la base (c'est le cas que la purge existait pour servir)."""
    ticket = ticket_isole()

    cwd = dispatch.reisolate(SLUG, ticket, str(repo))

    assert Path(cwd).is_dir() and (Path(cwd) / "README.md").is_file()
    apres = tickets.get_ticket(SLUG, ticket["id"])["worktree"]
    assert apres["ok"] and apres["branch"] == f"agent/{ticket['id']}"


def test_le_travail_non_commite_est_recolte_avant_la_relance(repo, ticket_isole):
    """Le worktree est DÉTRUIT par la re-provision : ce qui y traîne doit d'abord être
    commité sur la branche, sinon la relance efface aussi le travail non commité."""
    ticket = ticket_isole()
    (Path(ticket["worktree"]["worktree"]) / "en_cours.py").write_text("y = 2\n",
                                                                     encoding="utf-8")

    cwd = dispatch.reisolate(SLUG, ticket, str(repo))

    assert (Path(cwd) / "en_cours.py").read_text(encoding="utf-8") == "y = 2\n"


def test_discard_stale_sauvegarde_avant_de_supprimer(repo, ticket_isole):
    """Chemin bas niveau : si la branche doit disparaître, son tip est d'abord tagué.
    Une destruction silencieuse est inacceptable même ici."""
    ticket = ticket_isole(livraison="x = 1\n")
    tip = git(ticket["worktree"]["worktree"], "rev-parse", "HEAD")

    resultat = worktrees.discard_stale(str(repo), ticket["id"], base_branch="develop")

    assert resultat["rescue_tag"], "aucune sauvegarde posée avant la suppression"
    assert git(repo, "rev-parse", resultat["rescue_tag"]) == tip
    assert commit_reachable(repo, tip)


def test_discard_stale_ne_tague_rien_quand_il_n_y_a_rien_a_sauver(repo, ticket_isole):
    """Le filet ne doit pas polluer le dépôt de tags pour des branches vides."""
    ticket = ticket_isole()

    resultat = worktrees.discard_stale(str(repo), ticket["id"], base_branch="develop")

    assert resultat["rescue_tag"] == ""
    assert git(repo, "tag", "-l") == ""
