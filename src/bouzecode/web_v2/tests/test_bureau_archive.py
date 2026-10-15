"""Le Bureau, file « on m'attend » : ARCHIVER une carte que je ne veux plus voir.

Pourquoi cette route existe : une carte posée par un agent mort reste dans « on m'attend »
indéfiniment. Vu le 2026-08-30 : une carte de 31 jours, incomplète (« l'agent n'a pas dit :
recommended, bloque, reversible, defaut_si_silence »), sans agent à débloquer — impossible d'y
« répondre » (personne n'écoute), et la subir masque les vraies décisions du jour.

Archiver n'EFFACE rien : la carte prend `delivery='moot'` (le « sans objet » qui existait déjà
pour la mort d'agent), donc elle sort de `open_decisions` en gardant sa trace.

Ces tests tapent les VRAIES routes et le VRAI JS servi : aucun mock. L'isolation DB/fichiers
vient de la fixture autouse `_isolate_production_state` du conftest de ce dossier.
"""
import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import decisions


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _carte(**kw):
    """Une carte que plus personne ne viendra débloquer : vieille, pauvre, sans options."""
    defauts = dict(
        source="agent",
        situation="digest_incomplet",
        question="J'ai besoin que tu fasses une intégration complète du portage",
        agent_id="9d0789f2fdca",
        project_slug="demo-application",
        ticket_id="642e1a3f",
        context="",
        options=[],
        allow_freetext=True,
        recommended="",
        urgency=1,
    )
    defauts.update(kw)
    return decisions.upsert(**defauts)


def _ouvertes(client):
    return [d["id"] for d in client.get("/api/decisions").get_json()["decisions"]]


def test_archiver_sort_la_carte_de_ma_file_sans_la_supprimer(client):
    """Le geste demandé : un bouton, la carte disparaît de « on m'attend », la trace reste."""
    carte = _carte()
    assert carte["id"] in _ouvertes(client), "préalable : la carte doit d'abord m'attendre"

    reponse = client.post(f"/api/decisions/{carte['id']}/archive")

    assert reponse.status_code == 200
    corps = reponse.get_json()
    assert corps["decision"]["delivery"] == "moot", \
        "archiver = rendre la carte sans objet, pas la répondre"
    assert not corps["decision"]["answered_at"], \
        "archiver ne doit PAS inventer une réponse humaine qui n'a jamais été donnée"
    assert carte["id"] not in _ouvertes(client), "une carte archivée ne doit plus m'attendre"
    assert decisions.get(carte["id"]) is not None, "la carte est archivée, pas supprimée"


def test_archiver_une_carte_inconnue_ne_plante_pas(client):
    reponse = client.post("/api/decisions/inconnue/archive")

    assert reponse.status_code == 404
    assert reponse.get_json()["error"]["code"] == "not_found"


def test_archiver_une_carte_deja_repondue_est_refuse(client):
    """Masquer une réponse déjà donnée cacherait un échec de livraison (invariant I3)."""
    carte = _carte(situation="digest_repondu")
    client.post(f"/api/decisions/{carte['id']}/answer", json={"answer_text": "vu"})

    reponse = client.post(f"/api/decisions/{carte['id']}/archive")

    assert reponse.status_code == 409
    assert reponse.get_json()["error"]["code"] == "already_answered"


def test_archiver_deux_fois_reste_sans_effet_de_bord(client):
    """Double-clic : la seconde fois ne doit ni 500 ni ressusciter la carte."""
    carte = _carte(situation="digest_double")
    client.post(f"/api/decisions/{carte['id']}/archive")

    seconde = client.post(f"/api/decisions/{carte['id']}/archive")

    assert seconde.status_code == 200
    assert seconde.get_json()["decision"]["delivery"] == "moot"
    assert carte["id"] not in _ouvertes(client)


def test_l_archivage_n_a_plus_d_ecran_depuis_la_suppression_des_categories(client):
    """L'archivage vivait dans une carte de décision, dans la file « On m'attend ».

    Cette file — comme les trois autres catégories du Bureau — a été SUPPRIMÉE à la demande
    de l'utilisateur le 2026-09-08 : elle redisait ce que les tags de `#lignes-filtres`
    disent déjà. `carteDecision` est partie avec elle, donc `decision-archive` et
    `decision-card` ne sont plus produits par personne.

    Ce test ne réclame donc plus un bouton : il GARDE le fait que l'écran n'en construit
    plus, pour qu'un futur agent ne remette pas du rendu de cartes dans un Bureau qui n'a
    plus de files. La route serveur, elle, reste prouvée par les tests ci-dessus (elle
    répond 200, elle est idempotente). Si l'archivage doit revenir à l'écran, sa place est
    la liste unifiée `#lignes` (lignes.js), pas une file supprimée.
    """
    #  Refonte v3 : les cartes de la boîte « À traiter » sont rendues par bureau/inbox.js ; elles
    #  agissent sur les AGENTS et les TÂCHES, jamais sur les anciennes cartes de décision.
    js = client.get("/static/js/bureau/inbox.js").get_data(as_text=True)
    assert js, "bureau/inbox.js doit être servi"

    assert "decision-archive" not in js, "le Bureau ne construit plus de carte de décision"
    assert "decision-card" not in js, "les cartes de décision ont été retirées avec les files"
