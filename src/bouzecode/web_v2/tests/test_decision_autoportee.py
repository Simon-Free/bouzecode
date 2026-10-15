# [desc] Une micro-tâche doit porter, seule, de quoi décider : options avec conséquence,
# ce que mon silence bloque, la réversibilité, le défaut si je ne réponds rien.
"""Ce test dit le CONTRAT vu de l'utilisateur du Bureau : en regardant une carte, il doit voir
exactement ce qu'il a à décider. Il tape les vraies routes et la vraie SQLite (fixture autouse
`_isolate_production_state` du conftest voisin) — rien n'est simulé.

Deux exigences symétriques :
- une carte bien remplie est déclarée COMPLÈTE et rend ses options structurées ;
- une carte pauvre (le cas des questions d'agent, qui n'ont ni conséquence ni recommandation)
  n'est PAS rejetée — elle est rendue avec la liste de ce qui manque, pour que l'écran puisse
  dire « l'agent n'a pas dit ce que je dois décider » au lieu de faire disparaître la question.
"""

from __future__ import annotations

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import decisions


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _riche(situation: str = "jet3_riche") -> dict:
    """La carte telle qu'un agent DEVRAIT l'écrire."""
    return decisions.upsert(
        source="test",
        situation=situation,
        question="Faut-il supprimer la table legacy des exports ?",
        context="ticket 42 — nettoyage du stockage",
        project_slug="bouzecode",
        ticket_id="42",
        agent_id="agent-7",
        options=[
            {"key": "supprimer", "label": "Supprimer la table",
             "consequence": "les exports d'avant 2024 ne seront plus rejouables"},
            {"key": "garder", "label": "La garder",
             "consequence": "on continue de porter 2 Go inutiles"},
        ],
        recommended="garder",
        bloque="1 agent attend, le ticket 42 ne peut pas se terminer",
        reversible="non",
        defaut_si_silence="sans réponse de ta part, l'agent garde la table et continue",
        urgency=0,
    )


def _pauvre(situation: str = "jet3_pauvre") -> dict:
    """Le cas réel des questions d'agent : des libellés bruts, rien d'autre."""
    return decisions.upsert(
        source="agent_question",
        situation=situation,
        question="Cet agent attend une réponse.",
        options=["oui", "non"],
    )


def _par_id(payload: dict, decision_id: str) -> dict:
    trouve = [carte for carte in payload["decisions"] if carte["id"] == decision_id]
    assert trouve, f"carte {decision_id} absente de la file"
    return trouve[0]


def test_carte_riche_est_autoportee_et_complete(client):
    """Tout ce qu'il faut pour décider est rendu par l'API, et la carte est dite complète."""
    carte = _riche()
    lue = _par_id(client.get("/api/decisions").get_json(), carte["id"])

    assert lue["bloque"].startswith("1 agent attend")
    assert lue["reversible"] == "non"
    assert "garde la table" in lue["defaut_si_silence"]
    assert lue["recommended"] == "garder"
    assert lue["complete"] is True
    assert lue["manque"] == []


def test_options_sont_structurees_avec_leur_consequence(client):
    """Une option n'est pas un libellé : c'est un choix ET sa conséquence."""
    carte = _riche("jet3_riche_options")
    lue = _par_id(client.get("/api/decisions").get_json(), carte["id"])

    assert [option["key"] for option in lue["options"]] == ["supprimer", "garder"]
    consequences = {option["key"]: option["consequence"] for option in lue["options"]}
    assert "rejouables" in consequences["supprimer"]
    assert consequences["garder"]


def test_carte_pauvre_est_gardee_mais_signalee_incomplete(client):
    """On ne fait JAMAIS disparaître une question d'agent : on dit ce qui manque."""
    carte = _pauvre()
    lue = _par_id(client.get("/api/decisions").get_json(), carte["id"])

    assert lue["complete"] is False
    for element in ("consequence", "recommended", "bloque", "reversible",
                    "defaut_si_silence"):
        assert element in lue["manque"], f"{element} devrait être signalé manquant"


def test_options_texte_restent_lisibles(client):
    """Rétrocompatibilité : les cartes déjà en base ont des options en simple texte."""
    carte = _pauvre("jet3_pauvre_retro")
    lue = _par_id(client.get("/api/decisions").get_json(), carte["id"])

    assert [option["key"] for option in lue["options"]] == ["oui", "non"]
    assert [option["label"] for option in lue["options"]] == ["oui", "non"]
    assert all(option["consequence"] == "" for option in lue["options"])


def test_un_nouveau_tick_enrichit_une_carte_deja_connue(client):
    """L'agent qui repasse avec du contexte doit pouvoir compléter sa propre carte."""
    pauvre = _pauvre("jet3_enrichie")
    decisions.upsert(
        source="agent_question",
        situation="jet3_enrichie",
        question="Cet agent attend une réponse.",
        asked_at=pauvre["asked_at"],
        options=[{"key": "oui", "label": "oui", "consequence": "on lance la migration"}],
        recommended="oui",
        bloque="rien pour l'instant, l'agent poursuit",
        reversible="oui",
        defaut_si_silence="sans réponse, l'agent choisit oui dans 1 h",
    )

    lue = _par_id(client.get("/api/decisions").get_json(), pauvre["id"])
    assert lue["complete"] is True
    assert lue["options"][0]["consequence"] == "on lance la migration"


def test_repondre_reste_possible_sur_une_carte_autoportee(client):
    """La réponse en un clic ne régresse pas : la clé d'option débloque toujours l'agent."""
    carte = _riche("jet3_reponse")
    reponse = client.post(f"/api/decisions/{carte['id']}/answer",
                          json={"answer_key": "garder"})

    assert reponse.status_code == 200
    corps = reponse.get_json()
    assert corps["decision"]["answered_at"]
    assert corps["delivery"]["state"] in {"delivered", "failed", "n_a"}
