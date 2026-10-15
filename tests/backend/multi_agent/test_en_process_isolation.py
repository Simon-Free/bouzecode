# [desc] Isolation decidee par le parent pour un sous-agent TUI en process : deux enfants `worktree` en parallele ecrivent le meme fichier relatif, chacun dans SON worktree, sans chdir du process ; echec de provisionnement = refus explicite. [/desc]
"""Vrai git, vrais outils (Write, Bash, Read via execute_tool) ; seule la boucle LLM est
remplacee par un faux `_agent_run` qui joue les appels d'outils d'un enfant."""
from __future__ import annotations

import os
import subprocess

import pytest

from bouzecode.backend.agent.state import AgentState, TurnDone
from bouzecode.backend.core.tool_registry import execute_tool
from bouzecode.backend.multi_agent import outil_agent, outils_enfants
from bouzecode.backend.multi_agent.en_process.fiche import FINI
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents


def _enfant_qui_ecrit(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    """Ecrit `commun.txt` (chemin RELATIF), puis demande a Bash ou il se trouve, et relit."""
    state.messages.append({"role": "user", "content": prompt})
    yield TurnDone(10, 1)
    nom = prompt.split()[0]
    ecrit = execute_tool("Write", {"file_path": "commun.txt", "content": f"ecrit par {nom}\n"},
                         config)
    ou = execute_tool("Bash", {"command": "git rev-parse --show-toplevel"}, config)
    relu = execute_tool("Read", {"file_path": "commun.txt"}, config)
    state.final_answer = f"{nom}|{ou.strip()}|{'ecrit par ' + nom in relu}|{ecrit[:60]}"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def depot(tmp_path, monkeypatch):
    from bouzecode.web_v2.services.work import worktrees
    depot = tmp_path / "depot"
    depot.mkdir()
    _git("init", "-q", "-b", "develop", cwd=depot)
    (depot / "README.md").write_text("depart\n", encoding="utf-8")
    _git("add", "README.md", cwd=depot)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "depart", cwd=depot)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr("bouzecode.backend.multi_agent.task._agent_run", _enfant_qui_ecrit)
    monkeypatch.setattr("bouzecode.backend.multi_agent.en_process.execution._sauver",
                        lambda fiche: None)
    monkeypatch.chdir(depot)
    return depot


def _config_tui():
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    return registre, {"_tui_agents": registre, "model": "claude-opus-5",
                      "permission_mode": "accept-all"}


def test_deux_enfants_worktree_ecrivent_le_meme_fichier_chacun_chez_soi(depot):
    registre, config = _config_tui()
    for nom in ("alpha", "beta"):
        lance = outil_agent._agent_tool({"prompt": f"{nom} ecris", "isolation": "worktree",
                                         "background": True, "name": nom}, config)
        assert lance.startswith("Task ID"), lance
    for fiche in registre.sous_agents():
        outils_enfants._check_agent_result({"task_id": fiche.id, "wait": True}, config)
    resultats = {f.description: f.resultat.split("|") for f in registre.sous_agents()}
    assert all(f.etat == FINI for f in registre.sous_agents())
    racines = {nom: os.path.normcase(os.path.normpath(r[1])) for nom, r in resultats.items()}
    assert len(set(racines.values())) == 2
    for nom, racine in racines.items():
        assert racine != os.path.normcase(str(depot))
        assert open(os.path.join(racine, "commun.txt"), encoding="utf-8").read() == f"ecrit par {nom}\n"
        assert resultats[nom][2] == "True"  # Read relatif relit SON fichier
    assert not (depot / "commun.txt").exists()
    assert os.path.normcase(os.getcwd()) == os.path.normcase(str(depot))  # aucun chdir global
    taches = {f.description: f.tache for f in registre.sous_agents()}
    assert taches["alpha"].worktree_branch.startswith("agent/tui-")


def test_un_enfant_partage_ecrit_dans_le_dossier_du_parent(depot):
    registre, config = _config_tui()
    outil_agent._agent_tool({"prompt": "gamma ecris", "name": "gamma"}, config)
    assert (depot / "commun.txt").read_text(encoding="utf-8") == "ecrit par gamma\n"


def test_isolation_impossible_est_un_refus_explicite(tmp_path, monkeypatch, depot):
    registre, config = _config_tui()
    hors_git = tmp_path / "hors_git"
    hors_git.mkdir()
    monkeypatch.chdir(hors_git)
    refus = outil_agent._agent_tool({"prompt": "delta ecris", "isolation": "worktree"}, config)
    assert refus.startswith("Error: sous-agent REFUSÉ, aucun enfant n'a été créé")
    assert "pas un dépôt git" in refus
    assert registre.sous_agents() == [] and not (hors_git / "commun.txt").exists()
