# [desc] Un message mis en file n'est jamais perdu : il n'est retiré qu'une fois LU par l'agent, et signalé « non livré » si l'agent s'arrête avant. [/desc]
"""Reproduction déterministe de la course constatée au bac à sable.

Un message tapé pendant qu'un agent travaille est mis en file, puis livré à la fin du tour en
étant poussé dans le `followup.txt` du process resté chaud. Si ce process est évincé (ou tué)
AVANT d'avoir lu `followup.txt`, le message n'est lu par personne. Avant le correctif, la file
avait déjà été vidée et l'API avait répondu « ok » : le message disparaissait en silence.
"""
import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime import warmpool
from bouzecode.web_v2.runtime.runner import agent_arret, agent_fiche
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import file_messages, warm_pool
from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction
from bouzecode.web_v2.tests.test_v3_statut_des_taches import ecrire_agent


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _file(client, agent_id):
    return client.get(f"/api/agents/{agent_id}/queue").get_json()["items"]


def _followup(agent_id):
    return agent_fiche.AGENTS_DIR / f"{agent_id}.ipc" / "followup.txt"


def _mettre_en_file_puis_finir_le_tour(client, agent_id, texte):
    """Chemin de la FIN de tour : le message attend en file (process pas encore joignable
    en plein tour — sinon il irait dans sa boîte, cf. test_message_pendant_le_tour), puis
    part dans le followup.txt du process resté chaud."""
    ecrire_agent(agent_id, vivant=False, ipc="running")
    file_messages.mettre_en_file(agent_id, texte)
    ecrire_agent(agent_id, vivant=True, ipc="idle")        # tour fini, process resté chaud
    store.invalidate_status(agent_id)
    assert file_messages.livrer_si_pret(agent_id) == {"ok": True}
    assert _followup(agent_id).read_text(encoding="utf-8") == texte, "poussé au process chaud"


def test_un_message_pousse_mais_pas_encore_lu_reste_visible_en_livraison(client):
    _mettre_en_file_puis_finir_le_tour(client, "7a7b7c7d7e7f", "et les tests ?")
    items = _file(client, "7a7b7c7d7e7f")
    assert [(i["text"], i.get("statut")) for i in items] == [("et les tests ?", "en_livraison")]


def test_un_message_lu_par_l_agent_quitte_la_file(client):
    _mettre_en_file_puis_finir_le_tour(client, "8a8b8c8d8e8f", "pense au README")
    _followup("8a8b8c8d8e8f").unlink()                      # le process l'a lu (pop_text)
    assert _file(client, "8a8b8c8d8e8f") == []


def test_un_agent_arrete_avant_de_lire_rend_le_message_non_livre(client):
    _mettre_en_file_puis_finir_le_tour(client, "9a9b9c9d9e9f", "garde la compat")
    ecrire_agent("9a9b9c9d9e9f", vivant=False, ipc="finished")   # évincé avant lecture
    store.invalidate_status("9a9b9c9d9e9f")

    items = _file(client, "9a9b9c9d9e9f")
    assert [(i["text"], i.get("statut")) for i in items] == [("garde la compat", "non_livre")]
    assert not _followup("9a9b9c9d9e9f").exists(), "plus personne ne lira ce fichier"
    #  Un message non livré n'est pas renvoyé tout seul (l'arrêt a pu être voulu) : il attend
    #  un geste de l'utilisateur (« Renvoyer » ou « Ignorer »).
    assert file_messages.livrer_si_pret("9a9b9c9d9e9f") is None
    qid = items[0]["id"]
    assert client.delete(f"/api/agents/9a9b9c9d9e9f/queue/{qid}").status_code == 200
    assert _file(client, "9a9b9c9d9e9f") == []


def test_le_menage_du_pool_chaud_n_evince_pas_un_agent_qui_n_a_pas_lu_son_message(client, monkeypatch):
    autoriser_la_destruction(monkeypatch)
    _mettre_en_file_puis_finir_le_tour(client, "aa1b2c3d4e5f", "une précision")
    ecrire_agent("bb1b2c3d4e5f", vivant=True, ipc="idle")
    #  La politique LRU désigne les deux agents : seul celui qui n'attend rien doit partir.
    monkeypatch.setattr(warmpool, "decide_evictions",
                        lambda nodes, now, cap: ["aa1b2c3d4e5f", "bb1b2c3d4e5f"])
    tues = []
    monkeypatch.setattr(agent_arret, "kill_agent", lambda agent: tues.append(agent.agent_id))
    assert warm_pool.sweep_warm_pool() == ["bb1b2c3d4e5f"]
    assert tues == ["bb1b2c3d4e5f"]
