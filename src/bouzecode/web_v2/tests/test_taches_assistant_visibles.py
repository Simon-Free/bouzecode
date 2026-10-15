"""Une tache creee par l'assistant du Bureau doit APPARAITRE sur le Bureau, et ce qu'il clot
doit en sortir.

Symptome humain (2026-09-09) : l'assistant annonce « 14 taches creees » avec leurs
identifiants, et l'utilisateur ne voit RIEN. Seconde manche (audit du 2026-09-23, F-14) :
l'outil ecrivait alors des « puces » TO-DO pendant que l'ecran affichait les taches (micros) —
l'assistant ne voyait pas les lignes ecrites a l'ecran, et ce qu'il « closait » y restait.

L'outil parle desormais aux MEMES objets que l'ecran : `GET /api/lignes` est la preuve. Les
gestes qui touchent un agent (clore, lancer) passent par le serveur HTTP : on branche ici
l'appel de l'outil sur le client de test de la vraie app, sans mock du comportement.
"""
import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.app import create_app

TITRE = "Repondre a Clement sur la table des BRs de Focus"
CHANTIER = "BUREAU"


@pytest.fixture()
def client(monkeypatch):
    app = create_app()
    app.config["TESTING"] = True
    test_client = app.test_client()

    def http(methode, chemin, corps=None):
        reponse = test_client.open(chemin, method=methode, json=corps)
        if reponse.status_code >= 400:
            raise RuntimeError(f"HTTP {reponse.status_code} — {reponse.get_json()}")
        return reponse.get_json() or {}

    monkeypatch.setattr(bureau_tools, "_http", http)
    return test_client


def _titres(client, archivees=False):
    vue = client.get("/api/lignes").get_json()
    lignes = [l for c in vue["chantiers"] for l in c["lignes"]] + vue["non_rattachees"]
    return [l["titre"] for l in lignes
            if archivees or l["statut_ui"] not in ("faite", "abandonnee")]


def test_une_tache_creee_par_l_assistant_apparait_sur_le_bureau(client):
    resultat = bureau_tools.taches(action="creer", titre=TITRE,
                                   intent="il attend une reponse depuis le 26/06")
    assert resultat["ok"] is True, resultat
    assert resultat["tache"]["id"], "l'assistant doit rendre un identifiant a l'utilisateur"
    assert TITRE in _titres(client)


def test_la_tache_est_rangee_sous_le_chantier_annonce(client):
    bureau_tools.taches(action="creer", titre=f"{CHANTIER} : {TITRE}")
    vue = client.get("/api/lignes").get_json()
    groupes = {c["titre"]: [l["titre"] for l in c["lignes"]] for c in vue["chantiers"]}
    assert TITRE in groupes.get(CHANTIER, []), groupes


def test_une_tache_ecrite_a_l_ecran_est_vue_par_l_assistant(client):
    client.post("/api/micros", json={"titre": "ecrite par l'humain"})
    titres = [t["titre"] for t in bureau_tools.taches(action="lister")["taches"]]
    assert "ecrite par l'humain" in titres


def test_clore_retire_la_tache_du_bureau(client):
    cree = bureau_tools.taches(action="creer", titre=TITRE)
    ferme = bureau_tools.taches(action="clore", task_id=cree["tache"]["id"])
    assert ferme["ok"] is True, ferme
    assert TITRE not in _titres(client)
    assert TITRE in _titres(client, archivees=True), "clore n'efface rien, on archive"


def test_clore_accepte_aussi_le_titre_de_la_tache(client):
    bureau_tools.taches(action="creer", titre=TITRE)
    ferme = bureau_tools.taches(action="clore", task_id=TITRE)
    assert ferme["ok"] is True, ferme
    assert TITRE not in _titres(client)


def test_clore_une_tache_inconnue_le_dit(client):
    resultat = bureau_tools.taches(action="clore", task_id="jamais-vu")
    assert resultat["ok"] is False
    assert resultat["erreur"] == "not_found", resultat


def test_lancer_sans_depot_rend_le_refus_du_serveur(client):
    """Le lancement passe par la MEME route que le bouton : meme refus nomme."""
    cree = bureau_tools.taches(action="creer", titre=TITRE)
    lance = bureau_tools.taches(action="lancer", task_id=cree["tache"]["id"])
    assert lance["ok"] is False
    assert "dépôt" in lance["message"]


def test_preciser_et_deplacer(client):
    cree = bureau_tools.taches(action="creer", titre=TITRE)
    ident = cree["tache"]["id"]
    assert bureau_tools.taches(action="preciser", task_id=ident, texte="voir le mail du 3/09")["ok"]
    bouge = bureau_tools.taches(action="deplacer", task_id=ident, chantier="AUTRE")
    assert bouge["tache"]["chantier"] == "AUTRE"
    micro = client.get(f"/api/micros/{ident}").get_json()["micro"]
    assert "voir le mail du 3/09" in micro["prompt"]


def test_lister_rend_les_taches_visibles_et_pas_l_historique(client):
    bureau_tools.taches(action="creer", titre=TITRE)
    vue = bureau_tools.taches(action="lister")
    assert vue["ok"] is True
    assert [t["texte"] for t in vue["taches"]] == [TITRE], vue

    bureau_tools.taches(action="clore", task_id=TITRE)
    assert bureau_tools.taches(action="lister")["taches"] == []


def test_le_store_v1_tasks_n_est_plus_ecrit():
    """La simplification demandee : plus une seule ecriture dans le vieux store."""
    from bouzecode.web_v2.services.work import tasks as v1

    bureau_tools.taches(action="creer", titre=TITRE, intent="pourquoi")
    assert v1.list_tasks(include_closed=True) == []
