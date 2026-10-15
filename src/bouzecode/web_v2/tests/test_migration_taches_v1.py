"""Lot A bis — les tâches du Bureau v1 sont DÉPLACÉES vers les lignes (arbitrage « tu déplaces »).

Niveau réel : on crée des tâches par le service v1, on lance la migration, puis on relit l'écran
par `GET /api/lignes` — exactement ce que verra l'utilisateur. Aucune mock.
"""

from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import tache_v1_migration as migration
from bouzecode.web_v2.services.work import tasks as tasks_service


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as testeur:
        yield testeur


def _lignes(client) -> dict:
    reponse = client.get("/api/lignes")
    assert reponse.status_code == 200, reponse.get_data(as_text=True)
    return reponse.get_json()


def _toutes(vue: dict) -> list[dict]:
    lignes = list(vue["non_rattachees"])
    for chantier in vue["chantiers"]:
        lignes.extend(chantier["lignes"])
    return lignes


def _par_titre(vue: dict, titre: str) -> dict:
    trouvee = [ligne for ligne in _toutes(vue) if ligne["titre"] == titre]
    assert trouvee, f"ligne « {titre} » absente de l'écran : {[l['titre'] for l in _toutes(vue)]}"
    return trouvee[0]


def test_une_tache_v1_devient_une_ligne_de_l_ecran(client):
    """Ce qui vivait dans « À faire » se lit maintenant dans la liste unique."""
    tasks_service.create_task(title="porter le décodeur TRAF",
                              intent="le format 3 encode la date en BCD",
                              project_slug="demo_ingestion", owner="agent")
    assert migration.migrer_taches_v1() >= 1

    ligne = _par_titre(_lignes(client), "porter le décodeur TRAF")
    assert ligne["statut"] == "inactif"
    assert ligne["raison"] == "a_faire"
    #  Le `pourquoi` de la tâche v1 n'est pas perdu : il devient le corps du brief.
    assert "BCD" in ligne["corps"]
    assert ligne["projet_slug"] == "demo_ingestion"


def test_une_ligne_a_moi_sans_depot_devient_un_arbitrage_pas_une_section(client):
    """« À décider » cesse d'être une section : c'est une RAISON d'inactivité."""
    tasks_service.create_task(title="trancher le profil par défaut",
                              intent="personne n'a confirmé la règle", owner="moi")
    migration.migrer_taches_v1()

    ligne = _par_titre(_lignes(client), "trancher le profil par défaut")
    assert ligne["statut"] == "inactif"
    assert ligne["raison"] == "a_decider"


def test_une_tache_close_arrive_archivee(client):
    """297 tâches faites ne doivent pas réapparaître comme du travail à prendre."""
    tache = tasks_service.create_task(title="nettoyer les conversations de test",
                                      project_slug="bouzecode", owner="agent")
    tasks_service.close_task(tache["id"], outcome="fait")
    migration.migrer_taches_v1()

    ligne = _par_titre(_lignes(client), "nettoyer les conversations de test")
    assert ligne["statut"] == "archive"
    assert ligne["raison"] == "faite"


def test_rejouer_la_migration_ne_duplique_rien(client):
    """L'idempotence est la seule chose qui rend un déplacement rattrapable."""
    tasks_service.create_task(title="vérifier la maille ID_TRAIN",
                              project_slug="demo_monorepo", owner="agent")
    premier = migration.migrer_taches_v1()
    assert premier >= 1
    avant = len(_toutes(_lignes(client)))

    assert migration.migrer_taches_v1() == 0
    apres = _toutes(_lignes(client))
    assert len(apres) == avant
    assert [ligne["titre"] for ligne in apres].count("vérifier la maille ID_TRAIN") == 1


def test_etat_cible_est_pur_et_dit_la_regle():
    """La règle de correspondance se lit sans base : c'est elle qu'on relira dans six mois."""
    assert migration.etat_cible({"owner": "moi"}, False) == ("brouillon", True)
    #  Un dépôt connu rend la ligne prenable par un agent : ce n'est plus un arbitrage.
    assert migration.etat_cible({"owner": "moi", "project_slug": "bouzecode"}, False) \
        == ("brouillon", False)
    #  Un ticket déjà lié prouve que quelqu'un a pris le sujet.
    assert migration.etat_cible({"owner": "moi"}, True) == ("brouillon", False)
    assert migration.etat_cible({"closed_at": "2026-01-01", "outcome": "fait"}, False) \
        == ("faite", False)
    assert migration.etat_cible({"closed_at": "2026-01-01", "outcome": "abandon"}, False) \
        == ("abandonnee", False)
