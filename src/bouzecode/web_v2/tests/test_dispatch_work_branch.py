# [desc] « Travaille sur CETTE branche » : honoré, ou refusé en nommant l'occupant — jamais remplacé. [/desc]
"""Un manager qui demande qu'un agent travaille sur une branche EXISTANTE doit obtenir
exactement ça, ou un refus qu'il peut lire.

L'incident : le ticket disait « ta branche de travail = agent/c08d9758 ». Le seul paramètre
qui en approchait (`resume_branch`) veut dire « pars DE cette branche » : l'agent a reçu une
branche NEUVE `agent/8f90ede5`, y a fait le bon travail, rendu `VERDICT: OK` — et la branche
visée est restée intacte sans que rien ne le signale.

On crée le ticket par l'API RÉELLE (`POST /api/projects/{slug}/tickets`) sur un vrai dépôt git jetable : c'est
git qui répond, pas une simulation. Seul le spawn de process est remplacé."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.runtime.runner import agent_creation
from bouzecode.web_v2.services.work import fleet, projects, worktrees

SLUG = "projet"


# Identité passée par `-c` plutôt que par `git config` : écrire dans le .git/config d'un dépôt
# tout juste créé peut échouer (verrou) quand plusieurs workers xdist démarrent ensemble.
_IDENT = ["-c", "user.name=t", "-c", "user.email=t@t.t"]


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, f"git {' '.join(args)} : {done.stderr}"
    return done.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Un dépôt avec `develop` (la branche vive) et `feature/livree`, qui porte du travail."""
    root = tmp_path / "depot"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "develop", str(root)], capture_output=True)
    (root / "fichier.txt").write_text("gateway\n", encoding="utf-8")
    _git(root, "add", "fichier.txt")
    _git(root, *_IDENT, "commit", "-qm", "gateway")
    _git(root, "branch", "feature/livree")
    return root


@pytest.fixture()
def dispatch(monkeypatch, tmp_path, repo):
    """Lance un dispatch réel et renvoie {reponse, cwd} — `cwd` = où l'agent a été spawné."""
    from bouzecode.web_v2.app import create_app

    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    # La création reborne le warm-pool après chaque lancement : pas de ménage du parc ici.
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: None)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr(projects, "list_projects",
                        lambda: [{"slug": SLUG, "name": "P", "path": str(repo)}])
    monkeypatch.setattr(projects, "find",
                        lambda slug: {"slug": slug, "name": "P", "path": str(repo)})
    spawned: dict = {}
    monkeypatch.setattr(agent_creation, "create_agent",
                        lambda prompt, model, cwd, **kw: spawned.update(cwd=cwd)
                        or SimpleNamespace(agent_id="enfant-1"))

    app = create_app()
    app.config["TESTING"] = True

    def _post(**payload) -> dict:
        payload.setdefault("prompt", "mets à jour la couche stockage")
        payload.setdefault("title", "couche stockage")
        payload.setdefault("isolation", "worktree")
        payload.setdefault("defer", False)
        with app.test_client() as client:
            response = client.post(f"/api/projects/{SLUG}/tickets", json=payload)
        corps = response.get_json()
        if response.status_code == 400:  # refus : forme unique {"error": {"code", "message"}}
            corps = {"routed": False, "code": corps["error"]["code"],
                     "error": corps["error"]["message"]}
        else:
            assert response.status_code == 201, response.get_data(as_text=True)
            corps["routed"] = True
        return {"reponse": corps, "cwd": spawned.get("cwd", "")}

    return _post


# ── (a) une branche existante LIBRE est honorée ──────────────────────────────

def test_l_agent_travaille_sur_la_branche_demandee(dispatch, repo):
    """`work_branch` : l'agent est réellement SUR la branche demandée, pas sur une copie."""
    resultat = dispatch(work_branch="feature/livree")

    assert resultat["reponse"]["routed"] is True, resultat["reponse"]
    assert _git(Path(resultat["cwd"]), "rev-parse", "--abbrev-ref", "HEAD") == "feature/livree"


def test_les_commits_de_l_agent_atterrissent_sur_la_branche_demandee(dispatch, repo):
    """Ce que l'agent commite dans son worktree fait AVANCER la branche visée."""
    avant = _git(repo, "rev-parse", "feature/livree")
    worktree = Path(dispatch(work_branch="feature/livree")["cwd"])

    (worktree / "fichier.txt").write_text("gateway\ncorrection\n", encoding="utf-8")
    _git(worktree, "add", "fichier.txt")
    _git(worktree, *_IDENT, "commit", "-qm", "la correction attendue")

    assert _git(repo, "rev-parse", "feature/livree") != avant, "la branche visée n'a pas bougé"


def test_aucune_branche_neuve_n_est_creee_pour_le_ticket(dispatch, repo):
    """Pas de `agent/<ticket>` fantôme à côté : la branche demandée est la seule."""
    ticket_id = dispatch(work_branch="feature/livree")["reponse"]["ticket_id"]

    assert f"agent/{ticket_id}" not in _git(repo, "branch", "--list", "agent/*")


# ── (b) une branche déjà SORTIE ailleurs échoue bruyamment ───────────────────

@pytest.fixture()
def branche_occupee(repo, tmp_path):
    """Un autre agent a déjà sorti `feature/livree` dans SON worktree."""
    occupant = tmp_path / "worktree-voisin"
    _git(repo, "worktree", "add", "-q", str(occupant), "feature/livree")
    return occupant


def test_une_branche_deja_sortie_ailleurs_fait_echouer_le_dispatch(dispatch, branche_occupee):
    """Deux agents ne peuvent pas tenir la même branche : le dispatch est REFUSÉ."""
    reponse = dispatch(work_branch="feature/livree")["reponse"]

    assert reponse["routed"] is False
    assert "feature/livree" in reponse["error"]


def test_le_refus_nomme_le_worktree_occupant(dispatch, branche_occupee):
    """Le message dit QUI occupe la branche — sinon il n'est pas actionnable."""
    reponse = dispatch(work_branch="feature/livree")["reponse"]

    assert str(branche_occupee) in reponse["error"].replace("\\", "/").replace("//", "/") \
        or branche_occupee.name in reponse["error"]


def test_aucune_branche_de_repli_n_est_creee_apres_un_refus(dispatch, repo, branche_occupee):
    """Le refus ne laisse RIEN derrière : ni agent lancé, ni branche neuve inventée."""
    avant = _git(repo, "branch", "--list")

    resultat = dispatch(work_branch="feature/livree")

    assert resultat["cwd"] == "", "aucun agent ne doit être spawné"
    assert _git(repo, "branch", "--list") == avant


def test_une_branche_inexistante_est_refusee_par_son_nom(dispatch):
    """Une branche qui n'existe pas est un refus lisible, pas une branche créée au passage."""
    reponse = dispatch(work_branch="feature/jamais-vue")["reponse"]

    assert reponse["routed"] is False
    assert "feature/jamais-vue" in reponse["error"]


# ── (c) le cas nominal est intact ────────────────────────────────────────────

def test_un_ticket_ordinaire_recoit_toujours_sa_branche_neuve(dispatch, repo):
    """Sans `work_branch`, rien ne change : branche neuve `agent/<ticket>` depuis la vive."""
    resultat = dispatch()
    ticket_id = resultat["reponse"]["ticket_id"]

    assert _git(Path(resultat["cwd"]), "rev-parse", "--abbrev-ref", "HEAD") == f"agent/{ticket_id}"


def test_resume_branch_garde_sa_semantique_de_point_de_depart(dispatch, repo):
    """`resume_branch` reste un POINT DE DÉPART : branche neuve, mais partant de là."""
    resultat = dispatch(resume_branch="feature/livree")
    ticket_id = resultat["reponse"]["ticket_id"]

    assert _git(Path(resultat["cwd"]), "rev-parse", "--abbrev-ref", "HEAD") == f"agent/{ticket_id}"
