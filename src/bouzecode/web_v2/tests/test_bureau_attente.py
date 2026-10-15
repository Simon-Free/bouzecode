"""Le Bureau, file « on m'attend » (lot L1 : US-1 voir, US-2 répondre, US-3 ne rien perdre).

Ces tests tapent les VRAIES routes et le VRAI HTML servi : aucun mock. L'isolation DB/fichiers
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
    """Une carte de décision ouverte, telle qu'un agent la pose en attendant l'humain."""
    defauts = dict(
        source="agent",
        situation="question",
        question="Faut-il supprimer les worktrees abandonnés ?",
        agent_id="ag-42",
        project_slug="bouzecode",
        ticket_id="T-7",
        context="Nettoyer les worktrees",
        options=[{"key": "oui", "label": "Supprime", "description": "irréversible"},
                 {"key": "non", "label": "Garde", "description": "on verra plus tard"}],
        allow_freetext=True,
        recommended="oui",
        urgency=0,
    )
    defauts.update(kw)
    return decisions.upsert(**defauts)


# --- US-1 : je vois ce qui m'attend -----------------------------------------------------------


def test_une_carte_posee_par_un_agent_est_listee_avec_de_quoi_decider(client):
    """De quoi décider sans ouvrir le code : question, qui attend, depuis quand, options, reco."""
    carte = _carte()

    corps = client.get("/api/decisions").get_json()
    trouvee = [d for d in corps["decisions"] if d["id"] == carte["id"]]

    assert trouvee, "la carte ouverte n'est pas servie par /api/decisions"
    vue = trouvee[0]
    assert vue["question"] == "Faut-il supprimer les worktrees abandonnés ?"
    assert vue["agent_id"] == "ag-42"
    assert vue["ticket_id"] == "T-7"
    assert vue["asked_at"], "sans asked_at le front ne peut pas dire « depuis combien de temps »"
    assert [o["key"] for o in vue["options"]] == ["oui", "non"]
    assert vue["allow_freetext"] is True
    assert vue["recommended"] == "oui"


def test_une_carte_sans_recommandation_reste_affichable(client):
    """Les questions d'agent arrivent sans reco : l'absence ne doit pas casser le contrat."""
    carte = _carte(situation="question_libre", recommended="", options=[], allow_freetext=True)

    vue = [d for d in client.get("/api/decisions").get_json()["decisions"]
           if d["id"] == carte["id"]][0]

    assert vue["recommended"] == ""
    assert vue["options"] == []


# --- US-2 : je réponds en un geste ------------------------------------------------------------

def test_repondre_par_option_sort_la_carte_de_ma_file(client):
    carte = _carte()

    reponse = client.post(f"/api/decisions/{carte['id']}/answer", json={"answer_key": "oui"})

    assert reponse.status_code == 200
    corps = reponse.get_json()
    assert corps["decision"]["answered_at"], "la réponse doit être persistée"
    assert corps["delivery"]["state"] in {"delivered", "failed", "n_a"}
    restantes = [d["id"] for d in client.get("/api/decisions").get_json()["decisions"]]
    assert carte["id"] not in restantes, "une carte répondue ne doit plus m'attendre"


def test_repondre_en_texte_libre_est_accepte(client):
    carte = _carte(situation="question_texte")

    reponse = client.post(f"/api/decisions/{carte['id']}/answer",
                          json={"answer_text": "aucune des deux, fais plutôt un inventaire"})

    assert reponse.status_code == 200
    assert reponse.get_json()["decision"]["answered_at"]


def test_repondre_deux_fois_est_refuse_sans_ecraser(client):
    carte = _carte(situation="question_double")
    client.post(f"/api/decisions/{carte['id']}/answer", json={"answer_key": "oui"})

    seconde = client.post(f"/api/decisions/{carte['id']}/answer", json={"answer_key": "non"})

    assert seconde.status_code == 409
    assert seconde.get_json()["error"]["code"] == "already_answered"


def test_repondre_a_une_carte_inconnue_ne_plante_pas(client):
    reponse = client.post("/api/decisions/inconnue/answer", json={"answer_key": "oui"})

    assert reponse.status_code == 404
    assert reponse.get_json()["error"]["code"] == "not_found"


# --- US-3 : aucune réponse ne se perd dans les tuyaux -----------------------------------------

def test_les_reponses_non_livrees_sont_listables(client):
    """Le front a besoin de cette liste pour le bandeau « N réponses non livrées »."""
    reponse = client.get("/api/decisions/failed")

    assert reponse.status_code == 200
    assert isinstance(reponse.get_json()["decisions"], list)


def test_rejouer_une_livraison_reussie_est_refuse(client):
    """Anti-doublon : on ne renvoie pas deux fois la même réponse à l'agent."""
    carte = _carte(situation="question_retry")
    client.post(f"/api/decisions/{carte['id']}/answer", json={"answer_key": "oui"})
    #  L'agent « ag-42 » n'existe pas ici : la livraison réelle échoue toujours. On pose donc
    #  l'état « livré » par la même porte que le chemin de livraison, pour tester la garde.
    decisions.mark_delivery(carte["id"], "delivered")

    rejeu = client.post(f"/api/decisions/{carte['id']}/retry")

    assert rejeu.status_code == 409
    assert rejeu.get_json()["error"]["code"] == "not_failed"
