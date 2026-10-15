"""Une question d'agent doit se voir SUR LA LIGNE du Bureau, pas seulement dans la conversation.

Bug signalé le 2026-09-22 : « quand je lance un ticket et que la conversation me remonte une
question, ce n'est pas répercuté sur le ticket ». Le ticket, lui, est bien dérivé
« attend réponse » (cf. test_ticket_awaiting.py) — mais la vue LIGNES du Bureau compte ce
statut parmi les statuts ACTIFS et rend donc `en_cours` : à l'écran, un agent qui attend
l'humain est indiscernable d'un agent qui travaille, et la question n'est nulle part.
"""
from datetime import datetime, timedelta

from bouzecode.web_v2.services.work import bureau_lignes
from bouzecode.web_v2.services.work.etat_ticket import vue as projection
from bouzecode.web_v2.services.work.fsm import etats

#  Lot L2 : l'index des statuts porte la PROJECTION de `ticket.state` (etat_ticket.vue).
QUESTION = projection({"state": etats.AWAITING_INPUT})


def _ligne(statut_ticket, minutes=5):
    """Une ligne LANCÉE dont l'unique ticket vient de donner signe de vie."""
    at = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return {"id": 1, "texte": "Corriger le bureau", "etat": "lancee",
            "tickets": [{"slug": "bouzecode", "ticket_id": "T-7", "at": at,
                         "statut": statut_ticket}]}


def test_une_question_rend_la_ligne_actionnable():
    """L'agent attend une réponse : la ligne n'avance plus, elle attend l'humain."""
    assert bureau_lignes.statut_de(_ligne("attend réponse")) == ("inactif", "a_repondre")


def test_un_agent_qui_travaille_reste_en_cours():
    """Garde-fou : on ne transforme pas tout ticket actif en question."""
    assert bureau_lignes.statut_de(_ligne("en cours")) == ("en_cours", "")


def test_la_question_prime_sur_la_ligne_figee():
    """Une question vieille de deux jours reste une question, pas une ligne « figée »."""
    assert bureau_lignes.statut_de(_ligne("attend réponse", minutes=3 * 24 * 60)) == (
        "inactif", "a_repondre")


def test_la_question_est_jointe_a_la_ligne():
    """La ligne ne dit pas seulement « on te demande quelque chose » : elle dit QUOI.

    Sans le texte de la question, il faut retrouver la conversation à la main — c'est
    exactement le trajet que l'utilisateur a signalé comme cassé le 22/09.
    """
    from datetime import datetime as _dt

    from bouzecode.web_v2.services.work import bureau_lignes as bl

    vue = {"id": "m1", "etat": "lancee", "texte": "Nettoyer les worktrees",
           "tickets": [{"slug": "bouzecode", "ticket_id": "T-7"}]}
    statuts = {("bouzecode", "T-7"): QUESTION}
    questions = {("bouzecode", "T-7"): {
        "agent_id": "ag-42",
        "question": "On supprime les worktrees abandonnés ?",
        "options": [{"key": "oui", "label": "Supprime"}],
        "allow_freetext": True,
        "asked_at": "2026-09-22T09:00:00",
        "warm": True,
    }}
    ligne = bl._ligne(vue, _dt.now(), statuts, questions)
    assert ligne["raison"] == "a_repondre"
    assert ligne["question"]["question"] == "On supprime les worktrees abandonnés ?"
    assert ligne["question"]["agent_id"] == "ag-42"
    assert ligne["question"]["ticket_id"] == "T-7"
    assert ligne["question"]["slug"] == "bouzecode"
    assert ligne["question"]["options"][0]["label"] == "Supprime"
    assert ligne["question"]["warm"] is True


def test_une_question_sans_agent_retrouvable_garde_la_raison():
    """Agent purgé, question introuvable : la ligne reste actionnable, simplement muette.

    Le contraire (retomber sur « en cours ») remettrait le bug : un ticket bloqué sur un
    humain redeviendrait indiscernable d'un ticket qui travaille.
    """
    from datetime import datetime as _dt

    from bouzecode.web_v2.services.work import bureau_lignes as bl

    vue = {"id": "m2", "etat": "lancee", "texte": "Sans agent",
           "tickets": [{"slug": "bouzecode", "ticket_id": "T-8"}]}
    ligne = bl._ligne(vue, _dt.now(), {("bouzecode", "T-8"): QUESTION}, {})
    assert ligne["raison"] == "a_repondre"
    assert "question" not in ligne


def test_la_question_se_joint_meme_quand_le_projet_de_l_agent_est_inconnu():
    """La vraie configuration du parc : l'agent tourne dans un WORKTREE, pas dans le dépôt.

    Mesuré le 22/09 sur le parc réel : `awaiting.agents_awaiting_answer()` rend
    `project_slug=''` (le cwd `~/.bouzecode/worktrees/<projet>/<nom>` n'est reconnu par
    aucun projet enregistré) alors que la ligne du Bureau porte `slug='demo'`. Sans
    cette jointure tolérante, l'écran affichait « on me demande une réponse » sans JAMAIS
    afficher la question — le bug restait à moitié.
    """
    rows = [{"agent_id": "59693eb8b37c", "ticket_id": "83e222ab",
             "ticket_slug": "demo", "project_slug": "",
             "question": "Je n'ai aucun accès à ta boîte mail",
             "options": [], "allow_freetext": True, "warm": True}]
    index = bureau_lignes._index_questions(rows)
    assert index[("demo", "83e222ab")]["agent_id"] == "59693eb8b37c"
    assert index[("", "83e222ab")]["agent_id"] == "59693eb8b37c"

    vue = {"id": "m3", "etat": "lancee", "texte": "Mail de microéconomie",
           "tickets": [{"slug": "demo", "ticket_id": "83e222ab"}]}
    ligne = bureau_lignes._ligne(vue, datetime.now(),
                                 {("demo", "83e222ab"): QUESTION}, index)
    assert ligne["raison"] == "a_repondre"
    assert ligne["question"]["question"].startswith("Je n'ai aucun accès")


def test_un_agent_hors_ticket_n_encombre_pas_l_index():
    """Une question posée hors ticket ne peut se rattacher à aucune ligne : on l'ignore."""
    assert bureau_lignes._index_questions([{"agent_id": "libre", "question": "?"}]) == {}


def test_a_repondre_est_une_raison_declaree():
    """Sans ça, le compteur de chantier ignore les lignes qui attendent une réponse."""
    assert "a_repondre" in bureau_lignes.RAISONS
