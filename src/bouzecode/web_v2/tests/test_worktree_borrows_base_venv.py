"""Un worktree ne provisionne un venv QUE si le manager l'a demandé ; sinon il EMPRUNTE celui
du dépôt de base au lieu d'en fabriquer un.

Le défaut mesuré le 2026-07-30 : l'isolation `worktree` promet « pas de venv », et le serveur
tenait promesse — mais l'agent se retrouvait sans aucun environnement Python, et `uv` en créait
un dans le worktree au premier `uv run` (~1 Go). Constat : 11 des 21 tickets `worktree`
portaient un venv que personne n'avait demandé.

Le contrat d'isolation lui-même n'a pas changé : c'est toujours le manager qui choisit via le
paramètre `isolation` de l'outil `Agent`.

Aucun mock : de vrais dossiers de venv sur disque, les vraies fonctions de dispatch.
"""
import os
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime import venv_env
from bouzecode.web_v2.services.work import dispatch


def _make_venv(root: Path) -> Path:
    """Un venv CRÉDIBLE : c'est `pyvenv.cfg` qui fait qu'un interpréteur s'y reconnaît."""
    venv = root / ".venv"
    (venv / ("Scripts" if os.name == "nt" else "bin")).mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = ailleurs\n", encoding="utf-8")
    return venv


# --- quel venv pour quelle isolation (pur) ------------------------------------

def test_un_worktree_sans_venv_demande_emprunte_celui_du_depot(tmp_path, monkeypatch):
    """`isolation='worktree'` = pas de venv à soi → celui du dépôt de base est désigné."""
    monkeypatch.setattr(dispatch.repos, "repo_root", lambda path: str(tmp_path))

    emprunte = dispatch.base_venv_for("worktree", str(tmp_path))

    assert Path(emprunte) == tmp_path / ".venv"


def test_un_worktree_avec_venv_demande_n_emprunte_rien(tmp_path, monkeypatch):
    """`worktree+venv` : l'agent a le sien, provisionné dans son worktree."""
    monkeypatch.setattr(dispatch.repos, "repo_root", lambda path: str(tmp_path))

    assert dispatch.base_venv_for("worktree+venv", str(tmp_path)) == ""


def test_un_agent_shared_n_emprunte_rien(tmp_path, monkeypatch):
    """`shared` : son cwd EST le dépôt, il trouve le venv tout seul."""
    monkeypatch.setattr(dispatch.repos, "repo_root", lambda path: str(tmp_path))

    assert dispatch.base_venv_for("shared", str(tmp_path)) == ""


def test_le_venv_est_cherche_a_la_racine_du_depot_pas_du_projet(tmp_path, monkeypatch):
    """Un projet peut pointer un SOUS-DOSSIER du dépôt ; le venv, lui, est à la racine."""
    sous_dossier = tmp_path / "apps" / "portail"
    sous_dossier.mkdir(parents=True)
    monkeypatch.setattr(dispatch.repos, "repo_root", lambda path: str(tmp_path))

    assert Path(dispatch.base_venv_for("worktree", str(sous_dossier))) == tmp_path / ".venv"


# --- ce que l'agent reçoit dans son environnement -----------------------------

def test_l_agent_recoit_le_venv_du_depot_et_uv_cesse_d_en_creer_un(tmp_path):
    """Les trois variables qui comptent : `VIRTUAL_ENV` pour python/pytest, le PATH pour les
    exécutables, et `UV_PROJECT_ENVIRONMENT` — c'est celle-là qui empêche uv de fabriquer un
    `.venv` dans le worktree, la cause exacte du gigaoctet non demandé."""
    venv = _make_venv(tmp_path)

    env = venv_env.base_venv_env(str(venv), environ={"PATH": "/outils/git"})

    assert env["VIRTUAL_ENV"] == str(venv)
    assert env["UV_PROJECT_ENVIRONMENT"] == str(venv)
    assert env["PATH"].startswith(str(venv_env.venv_bin_dir(venv)))
    assert env["PATH"].endswith("/outils/git")  # PRÉFIXÉ : l'agent garde git, uv, le reste


def test_un_venv_de_base_absent_ou_casse_ne_pollue_rien(tmp_path):
    """Sans venv utilisable, on n'injecte RIEN : mieux vaut l'environnement par défaut qu'un
    `VIRTUAL_ENV` qui pointe dans le vide (un venv sans `pyvenv.cfg` refuse de démarrer)."""
    assert venv_env.base_venv_env(str(tmp_path / "jamais_cree")) == {}

    casse = tmp_path / ".venv"
    (casse / "Scripts").mkdir(parents=True)  # dossier présent, marqueur absent
    assert venv_env.base_venv_env(str(casse)) == {}


def test_le_venv_emprunte_est_rejoue_a_chaque_respawn(tmp_path):
    """L'emprunt est porté par la FICHE de l'agent, donc rejoué au respawn/continue — sinon un
    agent repris repartait sans environnement et uv recréait un venv dans le worktree."""
    from bouzecode.web_v2.runtime import runner

    venv = _make_venv(tmp_path)
    agent = runner.Agent(agent_id="a1", prompt="p", model="m", cwd=str(tmp_path),
                         pid=0, started_at="2026-07-30T10:00:00Z", base_venv=str(venv))

    env = runner._ticket_env(agent)

    assert env["VIRTUAL_ENV"] == str(venv)
    assert env["UV_PROJECT_ENVIRONMENT"] == str(venv)


# --- le provisionnement ne fabrique plus de venv par accident ------------------

def test_provisionner_un_worktree_ne_cree_aucun_venv_par_defaut(tmp_path, monkeypatch):
    """`worktrees.provision` avait `with_venv=True` par défaut : un appelant qui l'omettait
    infligeait un `uv sync --all-extras` non demandé. Le défaut ne coûte plus rien."""
    from bouzecode.web_v2.services.work import worktrees

    appels = []
    monkeypatch.setattr(worktrees, "_setup_venv",
                        lambda wt, root="": appels.append(wt) or worktrees.VENV_OK)
    monkeypatch.setattr(worktrees, "add_worktree_bounded",
                        lambda *a, **k: "")  # git worktree add : succès, sans git
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wt")

    worktrees.provision(str(tmp_path), "ticket01", base_branch="develop")

    assert appels == []  # aucun uv sync déclenché
