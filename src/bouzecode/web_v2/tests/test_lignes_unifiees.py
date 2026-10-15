"""Lot 2 — UNE seule liste, rangée par CHANTIER (macro-tâche).

Ce que l'utilisateur a demandé, et que ce fichier vérifie au niveau des VRAIES routes
HTTP (aucun mock, base isolée par la fixture autouse `_isolate_production_state`) :

- « merger à faire, à décider, la todo, c'est la même chose » : une seule liste, plus de
  sections par statut ;
- « il y a les macro-tâches… relier des lignes dans des sous-thématiques (qui ne sont pas
  des projets) » : le regroupement se fait par chantier, jamais par dépôt ;
- « des trucs archivés, en cours, et inactifs » : le statut est DÉDUIT (`en_cours`,
  `inactif` + sa raison, `archive`), jamais saisi ;
- arbitrage « tu vires » : aucune fenêtre de temps — une ligne ne s'évapore pas parce
  qu'elle a huit jours.
"""
import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import bureau_lignes


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _macro(client, titre, projets=None):
    reponse = client.post("/api/macros", json={"titre": titre, "projets": projets})
    assert reponse.status_code == 201, reponse.get_data(as_text=True)
    return reponse.get_json()["macro"]


def _ligne(client, titre, macro_id="", projet_slug=""):
    reponse = client.post("/api/micros", json={"titre": titre, "macro_id": macro_id,
                                               "projet_slug": projet_slug})
    assert reponse.status_code == 201, reponse.get_data(as_text=True)
    return reponse.get_json()["micro"]


def _lignes(client):
    reponse = client.get("/api/lignes")
    assert reponse.status_code == 200, reponse.get_data(as_text=True)
    return reponse.get_json()


def test_la_liste_unique_est_rangee_par_chantier(client):
    """Deux lignes d'un même chantier tiennent dans UNE section ; celle sans chantier a la sienne."""
    #  Une liste de slugs, pas une chaîne à virgules : c'est le contrat de la route.
    macro = _macro(client, "Refaire DEMODB sur databricks",
                   projets=["demo_ingestion", "demo_monorepo"])
    _ligne(client, "vérifier la maille ID_TRAIN", macro_id=macro["id"])
    _ligne(client, "porter le décodeur TRAF", macro_id=macro["id"])
    _ligne(client, "une idée sans chantier")

    vue = _lignes(client)
    chantier = next(c for c in vue["chantiers"] if c["titre"] == "Refaire DEMODB sur databricks")
    titres = [ligne["titre"] for ligne in chantier["lignes"]]
    assert "vérifier la maille ID_TRAIN" in titres
    assert "porter le décodeur TRAF" in titres

    #  Le chantier traverse PLUSIEURS dépôts : ce n'est pas un projet.
    assert len(chantier["projets"]) == 2

    orphelines = [ligne["titre"] for ligne in vue["non_rattachees"]]
    assert "une idée sans chantier" in orphelines
    assert vue["stats"]["lignes"] >= 3


def test_une_ligne_neuve_est_inactive_parce_qu_elle_reste_a_faire(client):
    """« À faire » n'est plus une section : c'est une RAISON d'inactivité, déduite."""
    cree = _ligne(client, "brancher la sonde de fraîcheur", projet_slug="bouzecode")
    ligne = next(l for l in _lignes(client)["non_rattachees"] if l["id"] == cree["id"])
    assert ligne["statut"] == "inactif"
    assert ligne["raison"] == "a_faire"


def test_aucune_fenetre_de_temps_ne_filtre_la_liste(client):
    """Arbitrage utilisateur « tu vires » : plus de 2 jours / semaine / tout."""
    vue = _lignes(client)
    assert "fenetre" not in vue["stats"]


def test_une_ligne_lancee_dont_le_ticket_a_fini_ne_dit_plus_ca_tourne():
    """Le bug du 08/09 : la conversation est TERMINÉE, l'écran affichait « ça tourne ».

    `statut_de` ne regardait que la DATE du dernier ticket relié, jamais son statut : tant
    que personne ne repassait `etat` de `lancee` à `faite`, l'écran mentait 24 h puis
    disait « figée ». Une ligne dont tous les tickets ont fini attend une RELECTURE.
    """
    from datetime import datetime

    from bouzecode.web_v2.services.work import bureau_lignes

    maintenant = datetime(2026, 9, 8, 14, 0, 0)
    fini = {"etat": "lancee", "tickets": [
        {"slug": "demo", "ticket_id": "604e3c7f",
         "at": "2026-09-08T13:53:03", "statut": "à relire"}]}
    assert bureau_lignes.statut_de(fini, maintenant) == ("inactif", "a_relire")

    #  Et une ligne dont un ticket tourne VRAIMENT continue de dire « ça tourne » :
    #  le correctif ne doit pas éteindre l'activité réelle.
    vivant = {"etat": "lancee", "tickets": [
        {"slug": "demo", "ticket_id": "aaaaaaaa",
         "at": "2026-09-08T13:53:03", "statut": "en cours"}]}
    assert bureau_lignes.statut_de(vivant, maintenant) == ("en_cours", "")


def test_un_chantier_montre_ses_deux_lignes_et_la_finie_ne_dit_plus_ca_tourne(client):
    """Le cas RÉEL du 08/09 : un chantier à deux lignes, l'une lancée dont l'agent a fini.

    Ce test couvre le CÂBLAGE (`collect_lignes` -> index des statuts de tickets -> `_ligne`
    -> `statut_de`), que le test pur ne touche pas : c'est là que le statut réel des tickets
    est joint à la ligne. Il vérifie AUSSI que la ligne « à faire » du même chantier sort
    bien de `/api/lignes` — le second symptôme rapporté (« elle est masquée »), qui n'était
    pas reproductible côté serveur.
    """
    from bouzecode.web_v2.services.work import micros as micros_service
    from bouzecode.web_v2.services.work import tickets as tickets_svc

    macro = _macro(client, "Finir l'assistant")
    finie = _ligne(client, "le travail est fait", macro["id"], "demo")
    restante = _ligne(client, "il reste ceci a faire", macro["id"], "demo")

    #  Un ticket dont l'agent a bel et bien tourné PUIS terminé son run : c'est l'état exact
    #  du ticket réel (run `work` fini, `done` jamais posé) qui s'affichait « ça tourne ».
    ticket = tickets_svc.create_ticket("demo", "le travail est fait", "brief")
    tickets_svc.add_run("demo", ticket, "agent-1", "work", "", typology="coder")
    #  Lot L2 : la fin du run est un ÉVÉNEMENT (hook de fin) qui amène le ticket à `delivered`.
    from bouzecode.web_v2.services.work import constats
    constats.fin_de_run("demo", ticket["id"], "agent-1", "final_answer", final_answer=True)
    assert micros_service.lier_ticket(finie["id"], "demo", ticket["id"]) is not None

    #  `etat` n'est PAS patchable par la route : une transition passe par la porte unique
    #  qui valide le diagramme (`marquer_etat`). On respecte ce design plutôt que de le
    #  contourner — et on évite la route de lancement, qui ferait tourner un vrai agent.
    assert micros_service.marquer_etat(finie["id"], "lancee") is not None

    donnees = _lignes(client)
    #  On retrouve le chantier par SON CONTENU : le regroupement est ce qu'on teste.
    chantier = next(c for c in donnees["chantiers"]
                    if any(l["id"] == finie["id"] for l in (c["lignes"] or [])))
    par_id = {l["id"]: l for l in chantier["lignes"]}
    assert set(par_id) == {finie["id"], restante["id"]}
    assert (par_id[finie["id"]]["statut"], par_id[finie["id"]]["raison"]) == ("inactif", "a_relire")
    assert (par_id[restante["id"]]["statut"],
            par_id[restante["id"]]["raison"]) == ("inactif", "a_faire")


def test_les_trois_statuts_sont_deduits_de_la_ligne():
    """`statut_de` est pure : un arbitrage humain, une archive et un lancement mort."""
    assert bureau_lignes.statut_de({"etat": "brouillon", "decision": True}) == (
        "inactif", "a_decider")
    assert bureau_lignes.statut_de({"etat": "faite"}) == ("archive", "faite")
    #  Lancée sans aucun ticket relié : ce n'est pas « ça tourne ».
    assert bureau_lignes.statut_de({"etat": "lancee", "tickets": []}) == ("inactif", "figee")
