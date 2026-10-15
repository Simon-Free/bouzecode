"""Après une reprise, l'activité doit dire ce que l'agent fait MAINTENANT.

Bug du 2026-09-29 (agent 989a1292c700, ticket 078afc08) : la question du tour 10 est
répondue par POST /api/agents/<id>/messages, l'agent enchaîne Bash / CheckAgentResult /
Grep / Read aux tours 11 à 15, et GET /api/agents/activity servait pourtant
`activity="AskUserQuestion"` à chaque tour. Le superviseur croyait l'agent en boucle sur
sa question. Deux causes, testées séparément ici :

1. le tour REPRIS (`loop.resume_paused`) n'annonçait aucun outil à l'IPC, contrairement à
   `execute_tool_calls` : plus aucun battement d'activité pendant toute la reprise ;
2. faute de battement, l'affichage retombait sur le dernier outil ENREGISTRÉ de la
   session — l'`AskUserQuestion` qui a suspendu le tour, donc justement le seul outil qui
   ne peut pas être « en cours » sous un état `running`.
"""
import json
import os

import pytest

from bouzecode.web_v2.services.work import activity


def _write_agent(agents_dir, agent_id, prompt, *, ipc_state=None, messages=None,
                 returncode=None):
    """Un vrai agent sur disque, avec l'état IPC que son process aurait écrit et les
    messages déjà sauvegardés dans sa session (d'où sort le repli `last_tool`)."""
    ipc_dir = agents_dir / f"{agent_id}.ipc"
    ipc_dir.mkdir(exist_ok=True)
    if ipc_state is not None:
        (ipc_dir / "state.json").write_text(json.dumps(ipc_state), encoding="utf-8")
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": prompt, "model": "claude-sonnet", "cwd": "",
        "pid": os.getpid(),  # pid vivant : c'est CE process de test
        "started_at": "2026-09-29T12:00:00Z", "returncode": returncode,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(ipc_dir), "parent": "",
    }), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(json.dumps({
        "messages": messages or [], "turn_count": 11, "saved_at": "2026-09-29 12:10:00",
    }), encoding="utf-8")
    from bouzecode.web_v2.runtime.runner import agent_fiche
    agent_fiche._list_agents_cache.clear()


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import meta_index, purge, store
    from bouzecode.web_v2.services.work import fleet

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", d / "deleted_sessions.json")
    monkeypatch.setattr(store, "CACHE_PATH", d / "index_cache.json")
    meta_index.reset_memo()
    store._status_cache.clear()
    fleet.clear_tree_cache()
    yield d
    agent_fiche._list_agents_cache.clear()
    fleet.clear_tree_cache()


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _rafraichir(agents_dir):
    """Le parc est caché quelques secondes : sans ce vidage, un état IPC réécrit au
    milieu du test resterait invisible — on croirait le bug corrigé (ou pas) à tort."""
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import meta_index, store
    from bouzecode.web_v2.services.work import fleet

    agent_fiche._list_agents_cache.clear()
    store._status_cache.clear()
    meta_index.reset_memo()
    fleet.clear_tree_cache()


# --- cause 1 : le tour repris doit battre, comme un tour normal -----------------

def test_le_tour_repris_annonce_les_outils_qu_il_demarre(tmp_path):
    """`resume_paused` exécute les outils restants du lot : ils doivent être publiés à
    l'IPC (`_ipc_activity_cb`) — exactement une fois par niveau — sinon l'observateur
    n'a plus AUCUN battement pendant la reprise et affiche le dernier outil vu, la
    question. Non-régression du chemin `resume_paused` -> `dag._execute_level`."""
    from types import SimpleNamespace

    from bouzecode.backend.agent import loop

    cible = tmp_path / "note.txt"
    cible.write_text("bonjour", encoding="utf-8")
    publie = []
    state = SimpleNamespace(messages=[], turn_count=11, context_state=None,
                            timing_entries=[])
    config = {"_ipc_activity_cb": publie.append, "model": "claude-sonnet"}
    pending = {
        "ask_tc_id": "ask1",
        "question": "Je restaure ou je déploie ?",
        "pending_tcs": [
            {"id": "ask1", "name": "AskUserQuestion", "input": {"question": "?"}},
            {"id": "r1", "name": "Read", "input": {"file_path": str(cible)}},
        ],
    }

    gen = loop.resume_paused(pending, "déploie", state, config, "system")
    try:
        for _event in gen:
            if publie:  # l'annonce précède l'exécution du niveau
                break
    finally:
        gen.close()  # on ne rappelle jamais le modèle : le tour s'arrête ici

    assert publie == [["Read"]]


# --- cause 2 : la question répondue n'est pas une activité (fonction pure) ------

def test_une_question_deja_repondue_n_est_jamais_l_outil_en_cours():
    """State `running` + dernier outil enregistré `AskUserQuestion` : le tour a
    forcément été REPRIS (sinon l'état serait `awaiting_input`). On ne sait pas ce que
    l'agent fait, on dit donc l'appel au modèle — pas la question déjà tranchée."""
    vue = activity.describe({"state": "running", "last_event_at": 900.0},
                            meta={"last_tool": "AskUserQuestion"}, now=960.0)

    assert vue["activity"] == "llm"
    assert "AskUserQuestion" not in vue["activity_label"]


# --- la vue servie par l'API, sur la séquence réelle ---------------------------

def test_apres_la_reprise_l_api_montre_l_outil_en_cours_et_plus_la_question(client, agents_dir):
    """Séquence du bug : question → réponse livrée → nouveaux outils."""
    import time

    lot_de_la_pause = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "1", "name": "Methodology"}, {"id": "2", "name": "Agent"},
        {"id": "3", "name": "AskUserQuestion"},
    ]}]
    _write_agent(agents_dir, "eeeeee", "Analyse du parc",
                 ipc_state={"status": "awaiting_input", "updated_at": time.time(),
                            "question": "Je restaure ou je déploie ?", "turn": 10},
                 messages=lot_de_la_pause)

    avant = client.get("/api/agents/activity").get_json()["agents"][0]
    assert avant["activity"] == "awaiting_input"
    assert avant["question"] == "Je restaure ou je déploie ?"

    # Réponse livrée : le process repart et bat avec ses VRAIS outils.
    (agents_dir / "eeeeee.ipc" / "state.json").write_text(json.dumps({
        "status": "running", "updated_at": time.time(), "turn": 12, "tools": ["Bash"],
    }), encoding="utf-8")
    _rafraichir(agents_dir)

    apres = client.get("/api/agents/activity").get_json()["agents"][0]
    assert apres["activity"] == "Bash"
    assert apres["question"] == ""


def test_entre_deux_tours_repris_l_api_ne_ressert_pas_la_question(client, agents_dir):
    """Frontière de tour : l'IPC est réécrit `running` SANS `tools` (c'est ce que fait
    `_ipc_turn_cb`) et la session n'a pas encore enregistré le tour repris. L'affichage
    doit rester honnête (appel au modèle), pas ressusciter la question."""
    import time

    lot_de_la_pause = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "1", "name": "Methodology"}, {"id": "2", "name": "AskUserQuestion"},
    ]}]
    _write_agent(agents_dir, "ffffff", "Analyse du parc",
                 ipc_state={"status": "running", "updated_at": time.time(), "turn": 13,
                            # question résiduelle d'un state.json plus ancien
                            "question": "Je restaure ou je déploie ?"},
                 messages=lot_de_la_pause)

    ligne = client.get("/api/agents/activity").get_json()["agents"][0]

    assert ligne["activity"] == "llm"
    assert ligne["question"] == ""
    assert "AskUserQuestion" not in ligne["activity_label"]
