"""La TODO (`TachesProjet`) est a l'agent PRINCIPAL d'un ticket ; un SOUS-AGENT (qui a un agent
parent) n'en a aucun outil : il rend compte a son parent."""
from __future__ import annotations

from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.tools import registration, taches_projet


def _principal(monkeypatch):
    for nom in ("BOUZECODE_PARENT", "BOUZECODE_AGENT_DEPTH", "BOUZECODE_BRIEF_HUMAIN"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", "alpha")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", "T-42")


def test_l_agent_principal_a_les_outils_todo(monkeypatch):
    _principal(monkeypatch)
    assert not taches_projet.est_sous_agent({})
    assert "TachesProjet" in registration.enabled_tools_for_profile("developer")


def test_une_tache_du_bureau_est_un_agent_principal(monkeypatch):
    _principal(monkeypatch)
    monkeypatch.setenv("BOUZECODE_PARENT", "bureau-assistant-1")
    monkeypatch.setenv("BOUZECODE_BRIEF_HUMAIN", "1")
    assert "TachesProjet" in registration.enabled_tools_for_profile("developer")


def test_un_lancement_par_le_dispatcher_est_un_agent_principal(monkeypatch):
    _principal(monkeypatch)
    monkeypatch.setenv("BOUZECODE_PARENT", "dispatcher:web")
    assert "TachesProjet" in registration.enabled_tools_for_profile("developer")


def test_un_sous_agent_n_a_pas_les_outils_todo(monkeypatch):
    _principal(monkeypatch)
    monkeypatch.setenv("BOUZECODE_PARENT", "agent-parent-7")
    assert taches_projet.est_sous_agent({})
    assert "TachesProjet" not in registration.enabled_tools_for_profile("developer")
    rendu = get_tool("TachesProjet").func({"action": "lister"}, {})
    assert rendu["erreur"] == "reserve_a_l_agent_principal"


def test_un_sous_agent_en_process_est_reconnu_a_sa_profondeur(monkeypatch):
    _principal(monkeypatch)
    rendu = get_tool("TachesProjet").func({"action": "explorer"}, {"_depth": 1})
    assert rendu["erreur"] == "reserve_a_l_agent_principal"
    monkeypatch.setenv("BOUZECODE_AGENT_DEPTH", "1")
    assert "TachesProjet" not in registration.enabled_tools_for_profile("developer")
