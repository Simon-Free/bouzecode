"""Le récap d'un passage dit, pour chaque point « reste à faire » / « à décider », la tâche qui
le porte — ou qu'aucune n'existe, avec « Créer la tâche ».

Cas réel (2026-09-24) : la carte « Passage #1 ✓ Terminé » listait « Reste à faire : Améliorer
la difficulté estimée » et « À décider : Étendre le scraping… » alors que le pont de clôture
avait créé les deux tâches ; l'utilisateur a cru que l'agent n'avait rien créé.

On fabrique l'état réel (fiche d'agent + session avec sa FinalAnswer, ticket relié à la tâche),
on joue le pont de clôture comme l'agent le déclenche en clôturant, puis on lit `/api/lignes`
comme le front. Chaque test crée son chantier et n'affirme que sur ses propres tâches.
"""
import uuid

import pytest

from bouzecode.web_v2.services.work import constats, micros, tickets
from bouzecode.web_v2.services.work.cloture_micros import ouvrir_micros_de_cloture
from bouzecode.web_v2.tests.test_v3_statut_des_taches import SLUG, client, ecrire_agent, ligne  # noqa: F401

RESTE = {"titre": "Améliorer la difficulté estimée",
         "corps": "La difficulté auto vient des points : la recalibrer sur les taux de réussite."}
DECISION = {"titre": "Étendre le scraping aux autres sources du catalogue",
            "corps": "Décider lesquelles valent un parser dédié.", "decision": True}


def _final(restantes):
    return {"answer": "Scraper livré.", "taches_terminees": ["scraper le Kangourou"],
            "taches_restantes": restantes}


def _passage_fini(restantes, cloturer=True):
    """Une tâche d'un chantier neuf, lancée, dont l'agent a clôturé avec `restantes` ; le pont
    de clôture tourne comme dans le process de l'agent (ticket et dépôt de l'environnement)."""
    chantier = micros.create_macro(f"Portail {uuid.uuid4().hex[:6]}")
    tache = micros.create_micro(titre="Scraper les énigmes", macro_id=chantier["id"])
    ticket = tickets.create_ticket(SLUG, "Scraper les énigmes", "go")
    agent_id = uuid.uuid4().hex[:12]
    tickets.add_run(SLUG, ticket, agent_id, "work", "m")
    micros.lier_ticket(tache["id"], slug=SLUG, ticket_id=ticket["id"])
    micros.marquer_etat(tache["id"], "lancee")
    ecrire_agent(agent_id, final=_final(restantes), ticket_id=ticket["id"])
    constats.fin_de_run(SLUG, ticket["id"], agent_id, "final_answer")  # hook de fin du run
    creees = ouvrir_micros_de_cloture(restantes, ticket_id=ticket["id"], slug=SLUG) if cloturer else []
    return chantier, tache, ticket["id"], creees


def _suites(client, tache_id):
    [passage] = ligne(client, tache_id)["passages"]
    return passage["recap"]["suites"]


def test_chaque_point_du_recap_designe_la_tache_creee_a_la_cloture_avec_son_statut(client):
    """« → tâche créée : Améliorer la difficulté estimée · brouillon » : le lien vient du pont
    de clôture, et le statut est celui de la tâche aujourd'hui."""
    _, tache, _, creees = _passage_fini([RESTE, DECISION])
    par_titre = {c["titre"]: c["id"] for c in creees}

    suites = _suites(client, tache["id"])

    [reste] = suites["reste"]
    [a_decider] = suites["a_decider"]
    assert reste == {"id": par_titre[RESTE["titre"]], "titre": RESTE["titre"], "lien": "creee",
                     "statut_ui": "brouillon", "libelle_statut": "À lancer"}
    assert (a_decider["id"], a_decider["statut_ui"], a_decider["lien"]) == \
        (par_titre[DECISION["titre"]], "a_decider", "creee")


def test_le_lien_tient_meme_si_la_tache_creee_est_renommee(client):
    """Le lien est enregistré, pas deviné par le titre : renommer la tâche ne le casse pas."""
    _, tache, _, [creee] = _passage_fini([RESTE])
    micros.update_micro(creee["id"], corps="Recalibrer la difficulté\n\navec les résultats officiels")

    [reste] = _suites(client, tache["id"])["reste"]

    assert (reste["id"], reste["titre"]) == (creee["id"], "Recalibrer la difficulté")


def test_un_point_deja_ouvert_dans_le_chantier_designe_la_tache_existante(client):
    """Le pont ne crée pas de doublon : le récap montre alors la tâche déjà ouverte."""
    chantier, tache, ticket_id, _ = _passage_fini([RESTE], cloturer=False)
    existante = micros.create_micro(titre=RESTE["titre"], macro_id=chantier["id"])

    assert ouvrir_micros_de_cloture([RESTE], ticket_id=ticket_id, slug=SLUG) == []
    [reste] = _suites(client, tache["id"])["reste"]

    assert (reste["id"], reste["lien"]) == (existante["id"], "existante")


def test_une_cloture_d_avant_le_lien_se_rattache_par_titre_exact(client):
    """Données existantes (aucun lien enregistré) : repli sur une tâche au titre EXACT du point,
    dans le chantier de la tâche ; un titre voisin ne suffit pas."""
    chantier, tache, _, _ = _passage_fini([RESTE, DECISION], cloturer=False)
    homonyme = micros.create_micro(titre=RESTE["titre"], macro_id=chantier["id"])
    micros.create_micro(titre="Étendre le scraping", macro_id=chantier["id"])

    suites = _suites(client, tache["id"])

    assert (suites["reste"][0]["id"], suites["reste"][0]["lien"]) == (homonyme["id"], "titre")
    assert suites["a_decider"] == [None]


def test_un_point_sans_tache_se_cree_depuis_la_carte_une_seule_fois(client):
    """« Aucune tâche créée » → « Créer la tâche » : elle naît dans le chantier du passage, avec
    le brief que l'agent avait écrit et son drapeau de décision ; un 2e clic rend la même."""
    chantier, tache, ticket_id, _ = _passage_fini([RESTE, DECISION], cloturer=False)
    assert _suites(client, tache["id"])["a_decider"] == [None]
    url = f"/api/micros/{tache['id']}/passages/{ticket_id}/suites"

    premiere = client.post(url, json={"libelle": DECISION["titre"], "decision": True})
    seconde = client.post(url, json={"libelle": DECISION["titre"], "decision": True})

    assert premiere.status_code == 201 and seconde.status_code == 200
    creee = premiere.get_json()["micro"]
    assert seconde.get_json() == {"ok": True, "deja": True, "micro": seconde.get_json()["micro"]}
    assert seconde.get_json()["micro"]["id"] == creee["id"]
    assert (creee["macro_id"], creee["projet_slug"], creee["decision"]) == (chantier["id"], SLUG, True)
    assert DECISION["corps"] in creee["corps"]
    [a_decider] = _suites(client, tache["id"])["a_decider"]
    assert (a_decider["id"], a_decider["lien"], a_decider["statut_ui"]) == \
        (creee["id"], "manuelle", "a_decider")


@pytest.mark.parametrize("corps, statut", [({"libelle": RESTE["titre"]}, 404),
                                           ({"libelle": "  "}, 400)])
def test_creer_la_tache_d_un_passage_inconnu_ou_sans_libelle_est_refuse(client, corps, statut):
    """Un passage qui n'appartient pas à la tâche, ou un point vide : refus lisible."""
    _, tache, ticket_id, _ = _passage_fini([RESTE], cloturer=False)
    passage = "inconnu0" if statut == 404 else ticket_id

    reponse = client.post(f"/api/micros/{tache['id']}/passages/{passage}/suites", json=corps)

    assert reponse.status_code == statut and reponse.get_json()["error"]


def test_la_carte_a_verifier_de_la_boite_porte_aussi_les_taches_liees(client):
    """« À traiter » montre le même récap que le passage : avec ses tâches liées."""
    _, tache, _, [creee] = _passage_fini([RESTE])

    cartes = client.get("/api/inbox").get_json()["items"]

    [carte] = [c for c in cartes if (c.get("tache") or {}).get("micro_id") == tache["id"]]
    assert carte["recap"]["suites"]["reste"][0]["id"] == creee["id"]
