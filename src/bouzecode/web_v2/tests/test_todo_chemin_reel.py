"""Le CHEMIN RÉEL de la déclaration : une vraie session sur disque, relue par la
source live de l'onglet TO-DO. Aucune doublure, aucun `patch` : on écrit les mêmes
fichiers que le runtime écrit vraiment ({id}.json + {id}.session.json), puis on
demande à `TodoSource` ce qu'un agent a déclaré. Trois livraisons vertes ont cassé
en production parce que les tests ne parlaient qu'à des faux objets."""
import json

import pytest


def _ecrire_agent(agents_dir, agent_id, session):
    """Écrit un vrai agent + sa session, exactement comme le runtime les pose."""
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id,
        "prompt": "Livrer l'onglet TO-DO",
        "model": "claude-sonnet",
        "cwd": "",
        "pid": 999_999_999,
        "started_at": "2026-08-27T10:00:00Z",
        "returncode": 0,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": "",
        "parent": "",
    }), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps(session), encoding="utf-8")
    (agents_dir / f"{agent_id}.out.log").write_text("log", encoding="utf-8")


@pytest.fixture()
def parc(tmp_path, monkeypatch):
    """Un parc d'agents RÉEL sur disque : une clôture déclarée, une ancienne, un actif."""
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import purge

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", d / "deleted_sessions.json")

    _ecrire_agent(d, "declare01", {
        "messages": [{"role": "assistant", "content": "ok"}],
        "final_answer": "Livré.",
        "taches_terminees": ["Gate de clôture posé", "Onglet TO-DO servi"],
        "taches_restantes": [
            {"macro": "Onglet TO-DO",
             "texte": "Brancher le bouton lancer sur le dispatch différé, "
                      "et confirmer avant de partir parce qu'un dispatch coûte."},
            {"macro": "Onglet TO-DO", "texte": "Trancher la rétention des puces "
                                               "abandonnées", "decision": True},
        ],
        "taches_declarees": True,
    })
    _ecrire_agent(d, "ancien001", {
        "messages": [{"role": "assistant", "content": "ok"}],
        "final_answer": "Terminé (clôture antérieure aux champs obligatoires).",
        "recap": {"points_ouverts": [{"texte": "Confirmer la maille ID_TRAIN"}]},
    })
    _ecrire_agent(d, "encours01", {
        "messages": [{"role": "assistant", "content": "a"},
                     {"role": "user", "content": "b"},
                     {"role": "assistant", "content": "c"}],
    })
    agent_fiche._list_agents_cache.clear()
    yield d


def test_declaration_reelle_relue_depuis_le_disque(parc):
    """Ce que l'agent a déclaré à la clôture est relu TEL QUEL, texte entier."""
    from bouzecode.web_v2.services.work.todo_live import TodoSource

    lu = TodoSource().taches("declare01")
    assert lu["taches_declarees"] is True
    assert lu["taches_terminees"] == ["Gate de clôture posé", "Onglet TO-DO servi"]
    assert len(lu["taches_restantes"]) == 2
    premiere = lu["taches_restantes"][0]
    assert premiere["macro"] == "Onglet TO-DO"
    assert premiere["texte"].endswith("un dispatch coûte.")
    assert "…" not in premiere["texte"]
    assert lu["taches_restantes"][1]["decision"] is True


def test_cloture_ancienne_rend_non_declare(parc):
    """Une session écrite AVANT les champs obligatoires ne dit pas « rien ne reste »."""
    from bouzecode.web_v2.services.work.todo_live import TodoSource

    lu = TodoSource().taches("ancien001")
    assert lu["taches_restantes"] is None
    assert lu["taches_declarees"] is False


def test_liste_vide_declaree_vaut_rien_ne_reste(parc, tmp_path, monkeypatch):
    """`[]` déclaré est une RÉPONSE : déclaré = vrai, et zéro puce."""
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.work.todo_live import TodoSource

    _ecrire_agent(parc, "vide0001", {
        "messages": [], "final_answer": "Rien ne reste.",
        "taches_terminees": ["Tout fait"], "taches_restantes": [],
        "taches_declarees": True,
    })
    agent_fiche._list_agents_cache.clear()
    lu = TodoSource().taches("vide0001")
    assert lu["taches_restantes"] == []
    assert lu["taches_declarees"] is True


def test_etat_agent_lu_sans_arbre_ni_git(parc):
    """L'agent qui tourne encore est vu ACTIF avec son tour, sans /api/agents/tree."""
    from bouzecode.web_v2.services.work.todo_live import TodoSource

    source = TodoSource()
    encours = source.etat_agent("encours01")
    assert encours["actif"] is True
    assert encours["tour"] == 2
    clos = source.etat_agent("declare01")
    assert clos["actif"] is False
