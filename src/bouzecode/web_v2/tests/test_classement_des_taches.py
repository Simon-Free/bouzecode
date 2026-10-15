# [desc] Marquer une tâche faite ailleurs, doublon ou caduque, avec un commentaire signé et daté ; Rouvrir garde l'historique ; jamais sur une tâche dont l'agent travaille — vu par l'écran (routes) et par l'assistant (outil Taches). [/desc]
"""Cas réel (Portail des énigmes, 2026-09-25) : « Corriger les 10 points » avait été fait par la
tâche principale, « Relire la livraison » doublait la carte « À vérifier ». Les classer d'un clic
« Faite » perdait OÙ c'était fait ; les laisser ouvertes encombrait le Bureau.

On passe par la vraie app (client Flask) et la vraie base isolée du conftest ; l'outil de
l'assistant est branché sur ce même client, comme en production sur le serveur local."""
from __future__ import annotations

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import micros
from bouzecode.web_v2.tests.aides_tickets import constater_tout
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (  # noqa: F401
    FINAL_ANSWER, client, ecrire_agent, ligne, tache_lancee,
)


@pytest.fixture()
def assistant(client, monkeypatch):
    """L'outil Taches de l'assistant, parlant au serveur comme en production."""
    monkeypatch.setattr(bureau_tools, "_http", lambda m, chemin, corps=None:
                        client.open(chemin, method=m, json=corps).get_json())
    return bureau_tools.taches


def _classer(client, micro_id, **corps):
    return client.post(f"/api/micros/{micro_id}/classer", json=corps)


# ------------------------------------------------------------------ geste de l'utilisateur


def test_marquer_faite_avec_un_commentaire_le_montre_sur_la_carte(client):
    principale = micros.create_micro(titre="Scraper les énigmes")
    suite = micros.create_micro(titre="Corriger les 10 points")

    r = _classer(client, suite["id"], motif="faite", de=principale["id"],
                 commentaire="fait lors du tour de retours du 25/09 (commit 0059681)")

    assert r.status_code == 200, r.get_json()
    carte = ligne(client, suite["id"])
    assert carte["statut_ui"] == "faite"
    c = carte["classement"]
    assert (c["motif"], c["auteur"]) == ("faite", "humain")
    assert c["commentaire"] == "fait lors du tour de retours du 25/09 (commit 0059681)"
    assert c["lien"] == {"id": principale["id"], "titre": "Scraper les énigmes"}
    assert c["at"]


def test_un_doublon_designe_la_tache_qui_porte_le_travail(client):
    gardee = micros.create_micro(titre="Étendre le scraping à d'autres sites")
    doublon = micros.create_micro(titre="Brancher d'autres sites sources")

    sans_cible = _classer(client, doublon["id"], motif="doublon", commentaire="même sujet")
    r = _classer(client, doublon["id"], motif="doublon", de=gardee["id"], commentaire="même sujet")

    assert sans_cible.status_code == 400 and sans_cible.get_json()["error"]["code"] == "lien_requis"
    assert r.status_code == 200
    carte = ligne(client, doublon["id"])
    assert carte["statut_ui"] == "abandonnee"
    assert carte["classement"]["libelle"] == "Doublon"
    assert carte["classement"]["lien"]["titre"] == "Étendre le scraping à d'autres sites"
    assert ligne(client, gardee["id"])["statut_ui"] == "brouillon", "l'original reste à faire"


def test_caduque_sans_lien(client):
    micro = micros.create_micro(titre="Trancher le worktree résiduel")

    _classer(client, micro["id"], motif="caduque", commentaire="le worktree n'existe plus")

    c = ligne(client, micro["id"])["classement"]
    assert (c["libelle"], c["lien"]) == ("Caduque", None)


def test_rouvrir_garde_l_historique_puis_on_peut_reclasser(client):
    autre = micros.create_micro(titre="La vraie tâche")
    micro = micros.create_micro(titre="Exporter les verdicts")
    _classer(client, micro["id"], motif="caduque", commentaire="plus utile")

    client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "brouillon"})
    rouverte = ligne(client, micro["id"])
    _classer(client, micro["id"], motif="doublon", de=autre["id"], commentaire="finalement doublon")
    reclassee = ligne(client, micro["id"])

    assert rouverte["statut_ui"] == "brouillon" and rouverte["classement"] is None
    assert [c["motif"] for c in rouverte["classements"]] == ["caduque"]
    assert rouverte["classements"][0]["rouvert_at"]
    assert reclassee["classement"]["motif"] == "doublon"
    assert [c["motif"] for c in reclassee["classements"]] == ["caduque", "doublon"]


def test_une_tache_deja_classee_ne_se_reclasse_pas_sans_rouvrir(client):
    micro = micros.create_micro(titre="Ligne")
    _classer(client, micro["id"], motif="caduque", commentaire="c1")

    r = _classer(client, micro["id"], motif="faite", commentaire="c2")

    assert r.status_code == 409 and r.get_json()["error"]["code"] == "deja_classee"
    assert "rouvre-la" in r.get_json()["error"]["message"]


def test_refus_sur_une_tache_dont_l_agent_travaille(client):
    ecrire_agent("c9b2c3d4e5f6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("refacto en cours", "c9b2c3d4e5f6")

    r = _classer(client, micro_id, motif="faite", commentaire="fait ailleurs")

    assert r.status_code == 409
    corps = r.get_json()
    assert corps["error"]["code"] == "agent_actif" and corps["error"]["details"]["agent_id"] == "c9b2c3d4e5f6"
    assert "Arrêter" in corps["error"]["message"] and "livraison" in corps["error"]["message"]
    assert ligne(client, micro_id)["statut_ui"] == "en_cours", "rien n'a bougé"


def test_une_livraison_a_verifier_peut_etre_classee_faite_ailleurs(client):
    """L'agent a fini (À vérifier) : plus personne ne travaille, le classement passe."""
    ecrire_agent("d9b2c3d4e5f6", final=FINAL_ANSWER)
    micro_id, _ = tache_lancee("corriger le login", "d9b2c3d4e5f6")
    constater_tout()  # lot L2 : la livraison est constatée par le watchdog

    r = _classer(client, micro_id, motif="faite", commentaire="repris et livré ailleurs")

    assert r.status_code == 200
    assert ligne(client, micro_id)["statut_ui"] == "faite"


# ------------------------------------------------------------------ geste de l'assistant


def test_l_assistant_marque_avec_commentaire_signe_assistant(client, assistant):
    principale = micros.create_micro(titre="Scraper les énigmes")
    suite = micros.create_micro(titre="Corriger les 10 points")

    rendu = assistant(action="marquer_faite", task_id=suite["id"], de=principale["id"],
                      commentaire="fait dans la tâche principale, tour de retours du 25/09")

    assert rendu["ok"], rendu
    c = ligne(client, suite["id"])["classement"]
    assert (c["auteur"], c["motif"]) == ("assistant", "faite")
    assert rendu["classement"]["lien"]["id"] == principale["id"]
    listees = assistant(action="lister", include_closed=True)["taches"]
    vue = next(t for t in listees if t["id"] == suite["id"])
    assert "commentaire de l'assistant" in vue["classement"]


def test_l_assistant_doit_dire_pourquoi(assistant):
    micro = micros.create_micro(titre="Ligne")

    rendu = assistant(action="marquer_caduque", task_id=micro["id"])

    assert rendu == {"ok": False, "erreur": "commentaire_requis", "message": rendu["message"]}
    assert micros.get_micro(micro["id"])["etat"] == "brouillon"


def test_l_assistant_recoit_un_refus_actionnable_sur_une_tache_active(assistant):
    ecrire_agent("e9b2c3d4e5f6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("en cours", "e9b2c3d4e5f6")

    rendu = assistant(action="marquer_doublon", task_id=micro_id,
                      de=micros.create_micro(titre="autre")["id"], commentaire="doublon")

    assert rendu["ok"] is False and rendu["erreur"] == "agent_actif"
    assert "e9b2c3d4e5f6" in rendu["message"]


def test_l_assistant_rouvre_et_l_historique_reste(client, assistant):
    micro = micros.create_micro(titre="Relire la livraison")
    assistant(action="marquer_caduque", task_id=micro["id"], commentaire="doublon de la carte")

    rendu = assistant(action="rouvrir", task_id=micro["id"])

    assert rendu["ok"] and rendu["tache"]["statut"] == "brouillon"
    historique = ligne(client, micro["id"])["classements"]
    assert historique[0]["rouvert_par"] == "assistant"
