# [desc] Parler à un agent PENDANT son tour (SPEC §4.10, §4.6) : message déposé dans sa boîte, lu à sa prochaine frontière de tour, repris s'il ne sera jamais lu ; précision d'une tâche ajoutée au brief ET transmise à son agent, avec sa lecture visible sur le Bureau. [/desc]
"""L'état RÉEL est fabriqué sur disque (fiche d'agent, IPC, ticket relié à la tâche) sous le parc
isolé du conftest ; l'agent qui « lit » sa boîte le fait avec la même fonction que le vrai
process (`ipc.relever_messages`)."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime import ipc
from bouzecode.web_v2.runtime.runner import agent_arret, agent_chaud, agent_fiche
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import file_messages, interruption, micros
from bouzecode.web_v2.tests.test_v3_statut_des_taches import ecrire_agent, ligne, tache_lancee


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _boite(agent_id):
    return ipc.from_dir(agent_fiche.AGENTS_DIR / f"{agent_id}.ipc")


def _file(client, agent_id):
    return client.get(f"/api/agents/{agent_id}/queue").get_json()["items"]


def _ecrire_pendant_le_tour(client, agent_id, texte):
    ecrire_agent(agent_id, vivant=True, ipc="running")
    r = client.post(f"/api/agents/{agent_id}/messages", json={"text": texte, "mode": "queue"})
    assert r.status_code == 202, r.get_data(as_text=True)
    assert r.get_json()["en_tour"] is True
    return r.get_json()["queue_id"]


def test_un_message_ecrit_pendant_le_tour_part_aussitot_dans_la_boite_de_l_agent(client):
    _ecrire_pendant_le_tour(client, "d1a2b3c4d5e6", "et pense au README")
    assert ipc.relever_messages(_boite("d1a2b3c4d5e6")) == ["et pense au README"]


def test_il_reste_en_attente_jusqu_a_ce_que_l_agent_le_lise(client):
    _ecrire_pendant_le_tour(client, "d2a2b3c4d5e6", "et les tests ?")
    assert [(i["text"], i["statut"]) for i in _file(client, "d2a2b3c4d5e6")] == [
        ("et les tests ?", "en_livraison")]
    ipc.relever_messages(_boite("d2a2b3c4d5e6"))          # frontière de tour : l'agent le lit
    assert _file(client, "d2a2b3c4d5e6") == []


def test_annuler_un_message_pas_encore_lu_le_retire_de_la_boite(client):
    qid = _ecrire_pendant_le_tour(client, "d3a2b3c4d5e6", "oublie ça")
    assert client.delete(f"/api/agents/d3a2b3c4d5e6/queue/{qid}").status_code == 200
    assert ipc.relever_messages(_boite("d3a2b3c4d5e6")) == []


def test_un_message_deja_lu_ne_s_annule_plus(client):
    qid = _ecrire_pendant_le_tour(client, "d4a2b3c4d5e6", "trop tard")
    ipc.relever_messages(_boite("d4a2b3c4d5e6"))
    assert client.delete(f"/api/agents/d4a2b3c4d5e6/queue/{qid}").status_code == 404


def test_un_message_ecrit_avant_le_premier_running_du_process_part_dans_sa_boite(client):
    """Process lancé, pas encore d'état IPC : l'UI le montre déjà au travail. Le message y
    était rangé en file ordinaire et n'arrivait qu'à la FIN du tour (e2e intermittent :
    message envoyé 20 ms avant le premier `running`, trois frontières de tour manquées)."""
    ecrire_agent("dba2b3c4d5e6", vivant=True, ipc="running")
    (agent_fiche.AGENTS_DIR / "dba2b3c4d5e6.ipc" / "state.json").unlink()
    r = client.post("/api/agents/dba2b3c4d5e6/messages", json={"text": "et demo-front", "mode": "queue"})
    assert r.status_code == 202 and r.get_json()["en_tour"] is True
    assert ipc.relever_messages(_boite("dba2b3c4d5e6")) == ["et demo-front"]


def test_un_message_en_file_part_dans_la_boite_des_que_le_tour_est_visible(client):
    """Écrit pendant `starting`, avant que le process soit connu : en file ordinaire. Dès que
    l'agent joue son tour, le suivi (/blocks, watchdog) le dépose : lu à la prochaine étape."""
    ecrire_agent("dca2b3c4d5e6", vivant=False, ipc="unknown")
    file_messages.mettre_en_file("dca2b3c4d5e6", "et les tests ?")
    assert [i.get("statut") for i in _file(client, "dca2b3c4d5e6")] == [None]
    ecrire_agent("dca2b3c4d5e6", vivant=True, ipc="running")
    assert file_messages.livrer_si_pret("dca2b3c4d5e6") is None, "le tour n'est pas coupé"
    assert [i["statut"] for i in _file(client, "dca2b3c4d5e6")] == ["en_livraison"]
    assert ipc.relever_messages(_boite("dca2b3c4d5e6")) == ["et les tests ?"]
    assert _file(client, "dca2b3c4d5e6") == [], "lu : il quitte la file"


def test_un_agent_qui_s_arrete_sans_l_avoir_lu_le_rend_a_la_file(client):
    """Fin de process (sous-agent non chaud, crash) avant la frontière : le message repasse en
    file ordinaire et partira par la reprise de l'agent — jamais perdu en silence."""
    _ecrire_pendant_le_tour(client, "d5a2b3c4d5e6", "garde la compat")
    ecrire_agent("d5a2b3c4d5e6", vivant=False, ipc="finished")
    items = file_messages.lister("d5a2b3c4d5e6")
    assert [(i["text"], i.get("statut")) for i in items] == [("garde la compat", None)]
    assert ipc.relever_messages(_boite("d5a2b3c4d5e6")) == [], "repris de la boîte"


def test_un_agent_arrete_a_la_main_ne_repart_pas_pour_un_message(client):
    _ecrire_pendant_le_tour(client, "d6a2b3c4d5e6", "encore une chose")
    ecrire_agent("d6a2b3c4d5e6", vivant=False, ipc=ipc.STATUS_KILLED_BY_SERVER)
    items = file_messages.lister("d6a2b3c4d5e6")
    assert [(i["text"], i.get("statut")) for i in items] == [("encore une chose", "non_livre")]


def test_un_agent_en_pause_sur_une_question_recoit_le_message_comme_reponse(client):
    _ecrire_pendant_le_tour(client, "d7a2b3c4d5e6", "SQLite")
    ecrire_agent("d7a2b3c4d5e6", vivant=True, ipc="awaiting_input")
    assert [i.get("statut") for i in file_messages.lister("d7a2b3c4d5e6")] == [None]


def test_un_agent_oisif_releve_sa_boite_comme_tour_suivant():
    """Un message déposé juste quand le tour finit n'attend pas : la boucle chaude le relève."""
    paths = ipc.from_dir(agent_fiche.AGENTS_DIR / "oisif.ipc")
    ipc.deposer_message(paths, "q1", "premier")
    ipc.deposer_message(paths, "q2", "second")
    assert ipc._wait_for_followup(paths, ttl_seconds=5, poll_interval=0.01) == "premier\n\nsecond"


def test_un_message_relaye_dit_d_ou_il_vient_et_a_quelle_heure(client):
    ecrire_agent("d8a2b3c4d5e6", vivant=True, ipc="running")
    file_messages.transmettre("d8a2b3c4d5e6", "le fichier s'appelle X.md", origine="assistant")
    (lu,) = ipc.relever_messages(_boite("d8a2b3c4d5e6"))
    entete, *reste = lu.split("\n")
    assert entete.startswith("[Précision de l'utilisateur, relayée par l'assistant du Bureau — ")
    assert entete.endswith("]") and ":" in entete[-7:], entete
    assert "CHANGEMENT DE CONSIGNE" in lu and "Methodology" in lu
    assert reste[-1] == "le fichier s'appelle X.md"


def test_interrompre_coupe_le_tour_et_garde_le_message_dans_la_boite(client, monkeypatch):
    ecrire_agent("d9a2b3c4d5e6", vivant=True, ipc="running")
    coupes = []
    monkeypatch.setattr(interruption, "interrompre", lambda agent: coupes.append(agent.agent_id)
                        or {"ok": True, "escalated": False})
    r = file_messages.transmettre("d9a2b3c4d5e6", "stop, autre piste", interrompre=True)
    assert r["interruption"] == {"ok": True, "escalated": False}
    assert coupes == ["d9a2b3c4d5e6"]
    assert ipc.relever_messages(_boite("d9a2b3c4d5e6")) == ["stop, autre piste"]


def test_l_interruption_ne_tue_pas_l_agent_qui_a_cede_puis_est_reparti(monkeypatch):
    """L'agent consomme la demande, retombe oisif et REPART aussitôt avec le message : il
    tient de nouveau un tour, mais ce n'est plus celui qu'on a coupé — on ne le tue pas."""
    ecrire_agent("dab2b3c4d5e6", vivant=True, ipc="running")
    agent = agent_fiche.load_agent("dab2b3c4d5e6")
    tues = []
    monkeypatch.setattr(agent_chaud, "is_mid_turn", lambda a: True)
    monkeypatch.setattr(agent_arret, "kill_agent", lambda a: tues.append(a) or {})
    monkeypatch.setattr(interruption.time, "sleep", lambda s: ipc.consume_cancel(_boite(agent.agent_id)))
    assert interruption.interrompre(agent) == {"ok": True, "escalated": False}
    assert tues == []


# ------------------------------------------------------------------ tâche du Bureau


def test_une_precision_sur_une_tache_en_cours_est_ajoutee_au_brief_et_transmise(client):
    ecrire_agent("e1a2b3c4d5e6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("écrire le rapport", "e1a2b3c4d5e6")
    r = client.post(f"/api/micros/{micro_id}/precisions",
                    json={"texte": "le fichier doit s'appeler BILAN.md", "auteur": "assistant",
                          "transmettre": True})
    assert r.status_code == 201, r.get_data(as_text=True)
    corps = r.get_json()
    assert [(t["agent_id"], t["ok"], t["en_tour"]) for t in corps["transmis"]] == [
        ("e1a2b3c4d5e6", True, True)]
    #  Le brief est complété : une relance future en tiendra compte.
    assert "Précisions ajoutées :" in micros.prompt_de(corps["micro"])
    assert "BILAN.md" in micros.prompt_de(corps["micro"])
    #  La carte le montre : horodaté, pas encore lu…
    (precision,) = ligne(client, micro_id)["precisions"]
    assert precision["created_at"] and precision["transmissions"][0]["statut"] == "en_attente"
    #  …puis lu, dès que l'agent l'a relevé à sa frontière de tour.
    (lu,) = ipc.relever_messages(_boite("e1a2b3c4d5e6"))
    assert "relayée par l'assistant du Bureau" in lu and lu.endswith("BILAN.md")
    file_messages.lister("e1a2b3c4d5e6")               # le suivi (watchdog, /blocks) le constate
    (precision,) = micros.get_micro(micro_id)["precisions"]
    assert precision["transmissions"][0]["statut"] == "lue"
    assert precision["transmissions"][0]["lu_at"]


def test_une_precision_reveille_un_agent_au_repos(client):
    """Au repos (process chaud oisif) : la précision part tout de suite, comme tour suivant."""
    ecrire_agent("e2a2b3c4d5e6", vivant=True, ipc="idle")
    micro_id, _ = tache_lancee("écrire le rapport", "e2a2b3c4d5e6")
    r = client.post(f"/api/micros/{micro_id}/precisions",
                    json={"texte": "ajoute une conclusion", "transmettre": True}).get_json()
    assert [(t["ok"], t["en_tour"]) for t in r["transmis"]] == [(True, False)]
    suivant = (agent_fiche.AGENTS_DIR / "e2a2b3c4d5e6.ipc" / "followup.txt").read_text(encoding="utf-8")
    assert suivant.startswith("[Précision de l'utilisateur, ajoutée depuis le Bureau — ")
    assert suivant.endswith("ajoute une conclusion")


def test_sans_transmettre_une_precision_ne_touche_pas_l_agent(client):
    ecrire_agent("e3a2b3c4d5e6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("écrire le rapport", "e3a2b3c4d5e6")
    r = client.post(f"/api/micros/{micro_id}/precisions", json={"texte": "note pour plus tard"})
    assert r.status_code == 201 and r.get_json()["transmis"] == []
    assert ipc.relever_messages(_boite("e3a2b3c4d5e6")) == []


def test_une_tache_close_garde_la_precision_sans_rien_transmettre(client):
    ecrire_agent("e4a2b3c4d5e6", vivant=True, ipc="idle")
    micro_id, _ = tache_lancee("écrire le rapport", "e4a2b3c4d5e6")
    micros.marquer_etat(micro_id, "faite")
    r = client.post(f"/api/micros/{micro_id}/precisions",
                    json={"texte": "trop tard", "transmettre": True}).get_json()
    assert r["transmis"] == []
    assert not (agent_fiche.AGENTS_DIR / "e4a2b3c4d5e6.ipc" / "followup.txt").exists()


def test_les_sous_agents_joignables_la_recoivent_aussi(client):
    ecrire_agent("e5a2b3c4d5e6", vivant=True, ipc="running")
    ecrire_agent("e6a2b3c4d5e6", vivant=True, ipc="running")
    enfant = agent_fiche.load_agent("e6a2b3c4d5e6")
    enfant.parent = "e5a2b3c4d5e6"
    agent_fiche._save(enfant)
    agent_fiche._list_agents_cache.clear()
    store.invalidate_status("e6a2b3c4d5e6")
    micro_id, _ = tache_lancee("orchestrer", "e5a2b3c4d5e6")
    r = client.post(f"/api/micros/{micro_id}/precisions",
                    json={"texte": "base SQLite", "transmettre": True, "sous_agents": True}).get_json()
    assert [t["agent_id"] for t in r["transmis"]] == ["e5a2b3c4d5e6", "e6a2b3c4d5e6"]
    assert ipc.relever_messages(_boite("e6a2b3c4d5e6"))[0].endswith("base SQLite")


# ------------------------------------------------------------------ précision renvoyée


def _preciser(client, micro_id, texte):
    return client.post(f"/api/micros/{micro_id}/precisions",
                       json={"texte": texte, "auteur": "assistant", "transmettre": True})


def test_la_meme_precision_renvoyee_aussitot_n_est_ni_ajoutee_ni_retransmise(client):
    """Assistant du Bureau : clôture refusée, il a rejoué `preciser` — l'agent l'a reçue 2 fois."""
    ecrire_agent("f1a2b3c4d5e6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("écrire le rapport", "f1a2b3c4d5e6")
    assert _preciser(client, micro_id, "le fichier doit s'appeler BILAN.md").status_code == 201

    r = _preciser(client, micro_id, "le fichier doit s'appeler  BILAN.md")

    assert r.status_code == 200 and r.get_json()["doublon"] is True
    assert r.get_json()["transmis"] == []
    assert micros.prompt_de(micros.get_micro(micro_id)).count("BILAN.md") == 1
    assert len(ipc.relever_messages(_boite("f1a2b3c4d5e6"))) == 1


def test_une_autre_precision_juste_apres_est_bien_transmise(client):
    """Contrôle négatif : seule une précision IDENTIQUE est un doublon."""
    ecrire_agent("f2a2b3c4d5e6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("écrire le rapport", "f2a2b3c4d5e6")
    _preciser(client, micro_id, "le fichier doit s'appeler BILAN.md")

    r = _preciser(client, micro_id, "et ajoute une conclusion")

    assert r.status_code == 201 and not r.get_json().get("doublon")
    assert len(ipc.relever_messages(_boite("f2a2b3c4d5e6"))) == 2


def test_la_meme_precision_redonnee_bien_plus_tard_est_un_rappel_voulu(client, monkeypatch):
    """Hors de la fenêtre courte, répéter une consigne est un choix de l'humain : on transmet."""
    from datetime import datetime, timedelta
    from bouzecode.web_v2.services.work import taches_actions
    ecrire_agent("f3a2b3c4d5e6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("écrire le rapport", "f3a2b3c4d5e6")
    _preciser(client, micro_id, "garde le ton neutre")
    plus_tard = datetime.now() + timedelta(seconds=taches_actions.FENETRE_DOUBLON_S + 60)
    monkeypatch.setattr(taches_actions, "_maintenant", lambda: plus_tard)

    r = _preciser(client, micro_id, "garde le ton neutre")

    assert r.status_code == 201
    assert len(ipc.relever_messages(_boite("f3a2b3c4d5e6"))) == 2
