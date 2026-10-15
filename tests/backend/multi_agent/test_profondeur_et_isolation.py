"""Sous-agents récursifs : profondeur bornée par `config.max_agent_depth` sur les trois chemins,
et isolation choisie par le parent transmise au serveur.

Les seams sont ceux de l'outil (`_web_dispatch`, `_web_wait_verdict`), comme les autres tests
du dispatch web ; aucun process n'est lancé.
"""
import pytest

from bouzecode.backend.multi_agent import outil_agent, profondeur


@pytest.fixture()
def web(monkeypatch):
    envoyes: list[dict] = []
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/9d0789f2fdca.ipc")
    monkeypatch.delenv(profondeur.ENV_PROFONDEUR, raising=False)
    config = {"_web_dispatch": lambda corps: envoyes.append(corps) or {
        "routed": True, "ticket_id": "t1", "project_name": "p", "typology": "coder"},
        "_web_wait_verdict": lambda *_: "VERDICT: OK"}
    return config, envoyes


def test_au_dela_de_la_profondeur_max_l_appel_est_refuse_sans_dispatch(web, monkeypatch):
    config, envoyes = web
    monkeypatch.setenv(profondeur.ENV_PROFONDEUR, "4")

    sortie = outil_agent._agent_tool({"prompt": "creuse", "background": True},
                               {**config, "max_agent_depth": 4})

    assert sortie.startswith("Error: sous-agent REFUSE") and "profondeur 4" in sortie
    assert envoyes == []


def test_sous_la_profondeur_max_le_dispatch_part(web, monkeypatch):
    config, envoyes = web
    monkeypatch.setenv(profondeur.ENV_PROFONDEUR, "3")

    sortie = outil_agent._agent_tool({"prompt": "creuse", "background": True},
                               {**config, "max_agent_depth": 4})

    assert not sortie.startswith("Error"), sortie
    assert len(envoyes) == 1


def test_la_profondeur_du_process_s_ajoute_a_celle_de_la_boucle(monkeypatch):
    monkeypatch.setenv(profondeur.ENV_PROFONDEUR, "1")
    config = {"_depth": 1, "max_agent_depth": 2}

    assert profondeur.profondeur_courante(config) == 2
    assert profondeur.refus_profondeur(config) is not None
    assert profondeur.env_enfant({"_depth": 0}) == {profondeur.ENV_PROFONDEUR: "2"}


def test_defaut_de_profondeur_max_est_quatre(monkeypatch):
    monkeypatch.delenv(profondeur.ENV_PROFONDEUR, raising=False)
    assert profondeur.profondeur_max({}) == 4
    from bouzecode.backend.core.config import DEFAULTS
    assert DEFAULTS["max_agent_depth"] == 4


@pytest.mark.parametrize("demande, attendu", [
    ({}, "shared"), ({"isolation": "worktree"}, "worktree"),
    ({"isolation": "worktree_venv"}, "worktree+venv"),
])
def test_l_isolation_choisie_par_le_parent_part_au_serveur(web, demande, attendu):
    config, envoyes = web
    outil_agent._agent_tool({"prompt": "ecris", "background": True, **demande}, config)
    assert envoyes[0]["isolation"] == attendu


def test_une_isolation_inconnue_est_refusee(web):
    config, envoyes = web
    sortie = outil_agent._agent_tool({"prompt": "x", "isolation": "docker"}, config)
    assert sortie.startswith("Error: isolation inconnue") and envoyes == []


def test_le_schema_de_l_outil_porte_l_isolation_et_sa_regle():
    from bouzecode.backend.core.tool_registry import get_tool
    schema = get_tool("Agent").schema
    propriete = schema["input_schema"]["properties"]["isolation"]
    assert propriete["enum"] == ["shared", "worktree", "worktree_venv"]
    assert "PARALLÈLE" in propriete["description"] and "DÉPENDANCES" in propriete["description"]
