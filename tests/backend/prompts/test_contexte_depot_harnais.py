"""Le contexte de session dit où vit le code de bouzecode lui-même.

Constat sur 70 sessions réelles : pour une tâche « dans bouzecode », l'agent (cwd = demo)
cherchait `PycharmProjects\\bouzecode` alors que le dépôt est `PycharmProjects\\demo\\bouzecode`,
et perdait 2 à 5 tours (une session a même modifié un autre dépôt). Le harnais SAIT où est son
propre code : il le dit.
"""
from pathlib import Path

import bouzecode
from bouzecode.backend.core.context import build_session_context, harness_repo

RACINE = Path(bouzecode.__file__).resolve().parents[2]


def test_hors_du_depot_le_contexte_donne_le_chemin_du_code_de_bouzecode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    contexte = build_session_context({})
    assert str(RACINE) in contexte
    assert "bouzecode" in contexte.lower()


def test_dans_le_depot_la_ligne_est_inutile(monkeypatch):
    monkeypatch.chdir(RACINE)
    contexte = build_session_context({})
    assert "Code de bouzecode" not in contexte


def test_un_worktree_nomme_aussi_son_depot_principal(tmp_path):
    principal = tmp_path / "PycharmProjects" / "demo" / "bouzecode"
    wt = tmp_path / ".bouzecode" / "worktrees" / "bouzecode" / "solo"
    (principal / ".git" / "worktrees" / "solo").mkdir(parents=True)
    wt.mkdir(parents=True)
    (wt / "pyproject.toml").write_text("[project]\nname='bouzecode'\n", encoding="utf-8")
    (wt / ".git").write_text(f"gitdir: {principal / '.git' / 'worktrees' / 'solo'}\n",
                             encoding="utf-8")
    racine, depot = harness_repo(wt)
    assert racine == wt
    assert depot == principal


def test_hors_git_rien_nest_invente(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    assert harness_repo(tmp_path) == (tmp_path, None)
    assert harness_repo(tmp_path / "absent") == (None, None)
