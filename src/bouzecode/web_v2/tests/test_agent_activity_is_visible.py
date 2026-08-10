"""Ce que fait un agent doit être LISIBLE : l'outil en cours, le tour, l'âge du dernier
battement, et le silence anormal d'un agent « en cours » qui ne bat plus.

Le défaut mesuré : l'agent eac1f0bef295 est resté « en cours » onze minutes en pilotant un
outil, sans que rien ne permette de le distinguer d'un agent bloqué.

Aucun mock : on écrit de VRAIS artefacts d'agent (dont l'état IPC que le process écrit
lui-même) et on joue la route HTTP réelle via le test_client Flask.
"""
import json

import pytest

from bouzecode.web_v2.services.work import activity


def _write_agent(agents_dir, agent_id, prompt, *, ipc_state=None, returncode=None):
    """Un vrai agent sur disque, avec l'état IPC que son process aurait écrit."""
    ipc_dir = agents_dir / f"{agent_id}.ipc"
    ipc_dir.mkdir(exist_ok=True)
    if ipc_state is not None:
        (ipc_dir / "state.json").write_text(json.dumps(ipc_state), encoding="utf-8")
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": prompt, "model": "claude-sonnet", "cwd": "",
        # pid vivant : c'est CE process de test (il tourne, forcément)
        "pid": __import__("os").getpid(),
        "started_at": "2026-07-30T10:00:00Z", "returncode": returncode,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(ipc_dir), "parent": "",
    }), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps({"messages": [], "turn_count": 1, "saved_at": "2026-07-30 10:00:00"}),
        encoding="utf-8")
    # `list_agents` est caché 3 s : sans ce vidage, un agent écrit APRÈS le boot de
    # l'application resterait invisible le temps du test.
    from bouzecode.web_v2.runtime import runner
    runner._list_agents_cache.clear()


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import meta_index, purge, store
    from bouzecode.web_v2.services.work import fleet

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", d / "deleted_sessions.json")
    monkeypatch.setattr(store, "CACHE_PATH", d / "index_cache.json")
    meta_index.reset_memo()
    store._status_cache.clear()
    fleet.clear_tree_cache()
    yield d
    runner._list_agents_cache.clear()
    fleet.clear_tree_cache()


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --- la phrase servie, sur des preuves déjà lues (fonction pure) ---------------

def test_un_agent_qui_execute_un_outil_le_dit_avec_son_anciennete():
    """« Bash en cours depuis 3 min » — l'outil publié par le process, et son âge."""
    status = {"state": "running", "tools": ["Bash"], "last_event_at": 1000.0, "ipc_turn": 9}

    vue = activity.describe(status, meta={}, now=1000.0 + 180)

    assert vue["activity"] == "Bash"
    assert vue["activity_label"] == "Bash en cours depuis 3 min"
    assert vue["turn"] == 9
    assert vue["idle_seconds"] == 180


def test_un_agent_sans_outil_en_cours_est_dans_un_appel_au_modele():
    """Aucun outil publié + process vivant = l'agent attend le modèle, et on le dit."""
    vue = activity.describe({"state": "running", "last_event_at": 500.0}, meta={}, now=512.0)

    assert vue["activity"] == "llm"
    assert vue["activity_label"] == "appel au modèle depuis 12 s"


def test_un_agent_lance_par_l_ancien_harnais_retombe_sur_le_dernier_outil_enregistre():
    """Sans battement d'activité (agent lancé avant ce mécanisme), on nomme le dernier
    outil VU dans la session — en disant clairement qu'il est daté."""
    vue = activity.describe({"state": "running", "last_event_at": 900.0},
                            meta={"last_tool": "Edit"}, now=960.0)

    assert vue["activity"] == "Edit"
    assert "dernier outil vu : Edit" in vue["activity_label"]


def test_un_agent_qui_attend_une_reponse_ne_pretend_pas_travailler():
    """Une attente se décrit par l'attente, jamais par le dernier outil : sinon on croit
    que l'agent avance alors qu'il attend l'utilisateur."""
    vue = activity.describe({"state": "awaiting_input", "last_event_at": 10.0},
                            meta={"last_tool": "Bash"}, now=20.0)

    assert vue["activity"] == "awaiting_input"
    assert vue["activity_label"] == "attend une réponse de l'utilisateur"


def test_un_silence_anormal_est_signale_sans_conclure_a_la_mort():
    """Un « en cours » qui ne bat plus depuis longtemps est SIGNALÉ (stale), ce qui
    n'est pas un verdict : l'agent peut tenir un outil légitimement long."""
    frais = activity.describe({"state": "running", "last_event_at": 0.0 + 1},
                              meta={}, now=1 + 30)
    muet = activity.describe({"state": "running", "last_event_at": 0.0 + 1},
                             meta={}, now=1 + activity.STALE_AFTER_SECONDS + 1)

    assert frais["stale"] is False
    assert muet["stale"] is True


def test_un_agent_termine_n_a_aucune_activite_a_raconter():
    """Sur un agent fini, « Bash il y a 3 jours » n'informe personne : champ absent."""
    assert activity.describe({"state": "finished", "last_event_at": 1.0}, meta={}) == {}


# --- la vue servie par l'API --------------------------------------------------

def test_la_surveillance_liste_les_agents_vivants_et_ce_qu_ils_font(client, agents_dir):
    """/api/agents/activity ne rend QUE les vivants, chacun avec sa phrase d'activité —
    l'agent terminé, qui forme l'essentiel du parc, n'y figure pas."""
    import time

    _write_agent(agents_dir, "aaaaaa", "Déployer sur Azure",
                 ipc_state={"status": "running", "updated_at": time.time(), "turn": 9,
                            "tools": ["Bash"]})
    _write_agent(agents_dir, "bbbbbb", "Ticket déjà livré", returncode=0)

    body = client.get("/api/agents/activity").get_json()

    par_id = {row["agent_id"]: row for row in body["agents"]}
    assert "bbbbbb" not in par_id  # terminé → hors de la surveillance
    assert par_id["aaaaaa"]["activity"] == "Bash"
    assert par_id["aaaaaa"]["turn"] == 9
    assert body["count"] == 1


def test_la_surveillance_met_en_tete_ce_qui_reclame_un_geste_humain(client, agents_dir):
    """Un agent qui attend une réponse passe devant : la première ligne doit être
    celle sur laquelle il faut agir."""
    import time

    _write_agent(agents_dir, "cccccc", "Zzz travaille",
                 ipc_state={"status": "running", "updated_at": time.time(), "turn": 2})
    _write_agent(agents_dir, "dddddd", "Aaa demande",
                 ipc_state={"status": "awaiting_input", "updated_at": time.time(),
                            "question": "Je restaure ou je déploie ?", "turn": 3})

    body = client.get("/api/agents/activity").get_json()

    assert body["agents"][0]["agent_id"] == "dddddd"
    assert body["agents"][0]["question"] == "Je restaure ou je déploie ?"
    assert body["awaiting"] == 1
