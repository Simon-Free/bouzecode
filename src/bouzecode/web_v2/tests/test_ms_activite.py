"""Lecture de l'activite Microsoft 365 (mails Outlook, chats Teams) sans process ni reseau.

`PowerShellTransport` accepte un `runner` injectable : on lui rend exactement ce que
`graph_activite.ps1` ecrirait sur stdout, et on verifie les arguments qu'il aurait recus.
C'est le contrat de bout en bout du cote python, sans tenant Microsoft.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import ms_activite
#  Les erreurs typees vivent dans `teams.graph_transport` (et NON dans `reader`) ;
#  `ms_activite` les re-exporte, on passe par lui : un seul chemin d'import a retenir.
from bouzecode.web_v2.services.work.ms_activite import TeamsAuthError


class _Runner:
    """Faux `powershell` : memorise les arguments, rend un JSON fixe."""

    def __init__(self, charge: dict, code: int = 0):
        self.charge = charge
        self.code = code
        self.args: list[str] = []

    def __call__(self, args):
        self.args = list(args)
        return self.code, json.dumps(self.charge), ""


def test_les_mails_recents_sont_lus_avec_la_fenetre_demandee():
    runner = _Runner({"value": [
        {"id": "m1", "subject": "Peux-tu relire le contrat ?", "received": "2026-09-01T08:00:00Z",
         "sender": "Marie", "preview": "il me faut ton retour", "web_link": "https://x",
         "is_read": False},
    ]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    mails = ms_activite.mails(fenetre="30j", transport=transport)

    assert [m["subject"] for m in mails] == ["Peux-tu relire le contrat ?"]
    assert mails[0]["sender"] == "Marie"
    #  L'action et la borne partent bien au script, et la borne est un ISO UTC.
    assert runner.args[:2] == ["-Action", "mail"]
    borne = runner.args[runner.args.index("-Since") + 1]
    assert borne.endswith("Z") and borne[4] == "-"


def _mail_long() -> str:
    """Un corps qui DEPASSE largement le `bodyPreview` de 250 caracteres de Graph."""
    return "Bonjour Simon, " + "voici la suite du message " * 80 + "fin du message"


def test_un_mail_precis_est_rendu_avec_son_corps_entier():
    """Le retour a la source : la liste ne rend qu'un apercu, un id rend le mail ENTIER.

    Sans ce chemin, un agent voit passer le mail de Nathan mais n'en lit que 250
    caracteres : il ne peut ni le citer ni y repondre, et doit demander a l'humain
    de recoller le texte (constat du 2026-09-21).
    """
    corps = _mail_long()
    runner = _Runner({"value": [
        {"id": "m1", "subject": "RE: Planification cours", "received": "2026-09-11T13:37:00Z",
         "sender": "Nathan", "body": corps, "web_link": "https://x", "is_read": True},
    ]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    mail = ms_activite.mail_complet("m1", transport=transport)

    assert mail["subject"] == "RE: Planification cours"
    assert mail["sender"] == "Nathan"
    #  Entier veut dire entier : le debut ET la fin, aucun `...` de troncature.
    assert mail["body"].lstrip().startswith("Bonjour Simon,")
    assert mail["body"].rstrip().endswith("fin du message")
    assert len(mail["body"]) > 1000
    #  Le mail est demande par son id, et la fenetre n'a plus de sens ici.
    assert runner.args[:2] == ["-Action", "mail"]
    assert runner.args[runner.args.index("-MessageId") + 1] == "m1"


def test_l_outil_mails_rend_le_corps_entier_du_mail_demande():
    """Meme contrat cote outil : `Mails(message_id=...)` rend le mail complet."""
    corps = _mail_long()
    runner = _Runner({"value": [
        {"id": "m1", "subject": "RE: Planification cours", "received": "2026-09-11T13:37:00Z",
         "sender": "Nathan", "body": corps, "web_link": "https://x", "is_read": True},
    ]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    reponse = bureau_tools.mails(message_id="m1", transport=transport)

    assert reponse["ok"] is True
    assert reponse["mail"]["subject"] == "RE: Planification cours"
    assert reponse["mail"]["body"].rstrip().endswith("fin du message")
    assert len(reponse["mail"]["body"]) > 1000


def test_l_outil_mails_sans_message_id_garde_son_comportement_de_liste():
    """Le corps entier est OPT-IN : sans `message_id`, rien ne change (apercus, plafond)."""
    runner = _Runner({"value": [
        {"id": "m1", "subject": "Peux-tu relire le contrat ?", "received": "2026-09-01T08:00:00Z",
         "sender": "Marie", "preview": "il me faut ton retour", "web_link": "https://x",
         "is_read": False},
    ]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    reponse = bureau_tools.mails(fenetre="30j", transport=transport)

    assert reponse["ok"] is True
    assert [m["subject"] for m in reponse["mails"]] == ["Peux-tu relire le contrat ?"]
    assert "mail" not in reponse
    #  La fenetre repart bien au script quand aucun mail precis n'est demande.
    assert "-Since" in runner.args


def test_les_chats_teams_recents_sont_lus_avec_leurs_messages():
    runner = _Runner({"value": [
        {"id": "c1", "topic": "Projet Demo", "kind": "group", "messages": [
            {"id": "x1", "created": "2026-09-02T09:00:00Z", "sender": "bouzecode",
             "body": "tu prends la migration ?"},
        ]},
    ]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    chats = ms_activite.conversations_teams(fenetre="7j", transport=transport)

    assert chats[0]["topic"] == "Projet Demo"
    assert chats[0]["messages"][0]["body"] == "tu prends la migration ?"
    assert runner.args[:2] == ["-Action", "chats"]
    assert "-Messages" in runner.args


def _chat_charge(rang: int) -> dict:
    """Un chat comme Graph le rend vraiment : 20 messages de HTML complet."""
    corps = "<div><p>" + ("bla bla bla " * 40) + "</p>&nbsp;<p>fin</p></div>"
    return {"id": f"c{rang}", "topic": f"Sujet {rang}", "kind": "group", "messages": [
        {"id": f"m{rang}-{n}", "created": f"2026-09-{(n % 28) + 1:02d}T09:00:00Z",
         "sender": "bouzecode", "body": corps} for n in range(20)]}


def test_le_volume_des_chats_est_borne_pour_ne_pas_noyer_l_assistant():
    """30 chats x 20 messages de HTML mesuraient 271 103 chars (2026-09-09) : l'assistant
    recevait ~78 000 tokens en un tour et ne repondait plus. La lecture doit tenir dans
    un budget, en le DISANT quand elle coupe."""
    runner = _Runner({"value": [_chat_charge(rang) for rang in range(30)]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    chats = ms_activite.conversations_teams(fenetre="30j", transport=transport)

    taille = len(json.dumps(chats, ensure_ascii=False))
    assert taille <= ms_activite.SORTIE_MAX, f"payload trop gros : {taille} chars"
    premier = chats[0]["messages"][0]
    #  Le HTML est converti en texte : l'assistant lit des phrases, pas des balises.
    assert "<" not in premier["body"] and "&nbsp;" not in premier["body"]
    assert len(premier["body"]) <= ms_activite.BODY_MAX + 1
    #  Toutes les conversations restent nommees, meme si leurs messages sont coupes.
    assert len(chats) == 30
    assert all(chat["topic"] for chat in chats)


def test_une_coupe_de_messages_est_annoncee_et_garde_les_plus_recents():
    """Couper en silence ferait croire a l'assistant qu'il a tout lu."""
    corps = "<p>" + ("mot " * 200) + "</p>"
    runner = _Runner({"value": [{"id": "c1", "topic": "Bruyant", "kind": "group", "messages": [
        {"id": f"m{n}", "created": f"2026-09-0{(n % 9) + 1}T09:00:00Z", "sender": "bouzecode",
         "body": corps} for n in range(20)]}]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    chats = ms_activite.conversations_teams(fenetre="30j", transport=transport,
                                            budget=2_000)

    garde = chats[0]["messages"]
    assert len(garde) < 20
    assert chats[0]["messages_omis"] == 20 - len(garde)
    #  Graph rend les messages du plus recent au plus ancien : on garde la tete.
    assert [m["id"] for m in garde] == [f"m{n}" for n in range(len(garde))]


def test_une_fenetre_inconnue_est_refusee_au_lieu_d_etre_devinee():
    transport = ms_activite.ActiviteTransport(runner=_Runner({"value": []}))
    with pytest.raises(ValueError):
        ms_activite.mails(fenetre="90j", transport=transport)


def test_le_rapport_mails_annonce_la_coupe_au_lieu_de_la_fenetre_demandee():
    """Le defaut du 2026-09-09 : `fenetre: 30j` annonce avec 3 jours de mails dedans.

    L'assistant n'avait AUCUN moyen de savoir que les 50 mails rendus ne couvraient pas
    le mois demande : il l'annonçait donc comme complet. Le rapport doit dire la
    couverture REELLE et nommer le plafond."""
    runner = _Runner({"value": [
        {"id": f"m{n}", "subject": f"sujet {n}", "received": f"2026-09-0{9 - n}T08:00:00Z",
         "sender": "Automatique", "preview": "x", "web_link": "https://x", "is_read": True}
        for n in range(3)], "has_more": True})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_mails(fenetre="30j", top=3, transport=transport)

    assert rapport["ok"] is True
    assert rapport["total"] == 3
    assert rapport["plafond"] == 3
    assert rapport["tronque"] is True
    #  La couverture reelle, pas la fenetre demandee : c'est CE que l'assistant doit citer.
    assert rapport["couverture_debut"].startswith("2026-09-07")
    assert rapport["couverture_fin"].startswith("2026-09-09")
    assert "2026-09-07" in rapport["avertissement"]
    assert "top" in rapport["avertissement"]
    assert [m["subject"] for m in rapport["mails"]] == ["sujet 0", "sujet 1", "sujet 2"]


def test_le_rapport_mails_ne_crie_pas_a_la_troncature_quand_tout_tient():
    runner = _Runner({"value": [
        {"id": "m1", "subject": "seul", "received": "2026-09-01T08:00:00Z", "sender": "Marie",
         "preview": "x", "web_link": "https://x", "is_read": False}], "has_more": False})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_mails(fenetre="30j", top=50, transport=transport)

    assert rapport["tronque"] is False
    assert rapport["avertissement"] == ""


def test_le_rapport_mails_deduit_la_coupe_sans_has_more():
    """Un vieux script (ou un transport factice) ne rend pas `has_more` : le plafond
    atteint EXACTEMENT reste un signal suffisant pour prevenir."""
    runner = _Runner({"value": [
        {"id": f"m{n}", "subject": f"s{n}", "received": "2026-09-09T08:00:00Z",
         "sender": "X", "preview": "x", "web_link": "", "is_read": True} for n in range(2)]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_mails(fenetre="30j", top=2, transport=transport)

    assert rapport["tronque"] is True


def test_le_rapport_chats_totalise_les_messages_omis_et_les_conversations_videes():
    """`messages_omis` par chat existait deja, mais noye : un total le rend visible."""
    corps = "<p>" + ("mot " * 200) + "</p>"
    runner = _Runner({"value": [
        {"id": f"c{c}", "topic": f"Chat {c}", "kind": "group", "messages": [
            {"id": f"c{c}m{n}", "created": f"2026-09-0{(n % 9) + 1}T09:00:00Z",
             "sender": "bouzecode", "body": corps} for n in range(20)]} for c in range(3)],
        "has_more": True})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_chats(fenetre="30j", top=3, transport=transport,
                                        budget=2_000)

    assert rapport["ok"] is True
    assert rapport["total"] == 3
    assert rapport["tronque"] is True
    assert rapport["messages_omis_total"] > 0
    assert rapport["messages_omis_total"] == sum(
        c.get("messages_omis", 0) for c in rapport["conversations"])
    assert rapport["conversations_vides"] == sum(
        1 for c in rapport["conversations"] if not c.get("messages"))
    assert "conversation_id" in rapport["avertissement"]


def test_un_consentement_refuse_remonte_en_erreur_d_authentification():
    """Le tenant peut refuser Mail.Read : l'outil doit le DIRE, pas inventer une reponse."""
    runner = _Runner({"error": {"code": "AuthenticationError",
                                "message": "AADSTS65001 consent required",
                                "action": "mail"}}, code=1)
    transport = ms_activite.ActiviteTransport(runner=runner)
    with pytest.raises(TeamsAuthError):
        ms_activite.mails(fenetre="30j", transport=transport)
