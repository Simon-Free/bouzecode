"""Cache disque par jour des lectures d'activite Microsoft 365.

Ces tests parlent au point d'entree REEL de l'assistant (`ActiviteTransport.mail_brut`,
`chats_brut`, ...) avec un faux `powershell` qui se comporte comme `graph_activite.ps1` :
il filtre son stock sur le `-Since` recu et COMPTE ses appels. Ce que l'on verifie n'est
donc pas une API interne mais le service rendu : « un jour revolu ne se re-telecharge
jamais, le jour courant toujours ».
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from bouzecode.web_v2.services.work.ms_activite import ActiviteTransport

#: Heure de reference des tests. Le jour courant est donc le 2026-09-25.
MAINTENANT = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)

MAIL_J3 = {
    "id": "m-j3",
    "subject": "Compte rendu",
    "received": "2026-09-22T09:00:00Z",
    "sender": "alice@example.com",
    "preview": "Voici le compte rendu",
    "web_link": "https://outlook/1",
    "is_read": True,
}
MAIL_J1 = {
    "id": "m-j1",
    "subject": "Relance",
    "received": "2026-09-24T08:00:00Z",
    "sender": "bob@example.com",
    "preview": "Tu as vu ?",
    "web_link": "https://outlook/2",
    "is_read": False,
}
MAIL_AUJOURDHUI = {
    "id": "m-j0",
    "subject": "Ce matin",
    "received": "2026-09-25T07:00:00Z",
    "sender": "carol@example.com",
    "preview": "Bonjour",
    "web_link": "https://outlook/3",
    "is_read": False,
}


class _RunnerGraph:
    """Faux `graph_activite.ps1` : filtre son stock sur `-Since`, compte les appels.

    Le vrai script filtre lui aussi sur la seule borne BASSE (`receivedDateTime ge
    $Since` pour les mails, `created -lt $Since -> continue` pour chats/canaux) : le
    faux doit se comporter pareil, sinon le test validerait un script imaginaire.
    """

    def __init__(self, mails=(), chats=(), canaux=(), has_more: bool = False):
        self.mails = list(mails)
        self.chats = list(chats)
        self.canaux = list(canaux)
        self.has_more = has_more
        self.appels: list[dict] = []

    def _params(self, args) -> dict:
        params = {}
        for rang in range(0, len(args) - 1, 2):
            nom = str(args[rang])
            if nom.startswith("-"):
                params[nom[1:]] = args[rang + 1]
        return params

    def __call__(self, args):
        params = self._params(list(args))
        self.appels.append(params)
        action = params.get("Action")
        depuis = params.get("Since")
        if action == "mail":
            gardes = [m for m in self.mails if depuis is None or m["received"] >= depuis]
            charge = {"value": gardes, "has_more": self.has_more}
        elif action == "chats":
            charge = {"value": self._conteneurs(self.chats, depuis), "has_more": self.has_more}
        elif action == "canaux":
            charge = {
                "value": self._conteneurs(self.canaux, depuis, garder_vides=True),
                "has_more": self.has_more,
                "messages_indisponibles": False,
            }
        else:
            charge = {"value": [], "has_more": False}
        return 0, json.dumps(charge), ""

    @staticmethod
    def _conteneurs(stock, depuis, garder_vides: bool = False):
        rendus = []
        for conteneur in stock:
            recents = [
                message
                for message in conteneur.get("messages", [])
                if depuis is None or message["created"] >= depuis
            ]
            if not recents and not garder_vides:
                continue
            copie = dict(conteneur)
            copie["messages"] = recents
            rendus.append(copie)
        return rendus


def _transport(runner) -> ActiviteTransport:
    return ActiviteTransport(runner=runner, maintenant=MAINTENANT)


def _since(appel: dict) -> str:
    return str(appel.get("Since"))


def test_jours_revolus_relus_du_disque():
    """Deuxieme lecture : PowerShell n'est relance que pour le jour courant, et les
    mails des jours passes sont quand meme rendus."""
    runner = _RunnerGraph(mails=[MAIL_AUJOURDHUI, MAIL_J1, MAIL_J3])

    premier = _transport(runner).mail_brut("2026-09-18T10:00:00Z")
    assert [m["id"] for m in premier["mails"]] == ["m-j0", "m-j1", "m-j3"]
    assert len(runner.appels) == 1

    second = _transport(runner).mail_brut("2026-09-18T10:00:00Z")
    assert len(runner.appels) == 2
    assert _since(runner.appels[1]) == "2026-09-25T00:00:00Z"
    assert [m["id"] for m in second["mails"]] == ["m-j0", "m-j1", "m-j3"]


def test_jour_courant_toujours_retelecharge():
    """Un mail arrive aujourd'hui apres la mise en cache doit apparaitre."""
    runner = _RunnerGraph(mails=[MAIL_J1, MAIL_J3])
    _transport(runner).mail_brut("2026-09-18T10:00:00Z")

    runner.mails.insert(0, MAIL_AUJOURDHUI)
    second = _transport(runner).mail_brut("2026-09-18T10:00:00Z")
    assert "m-j0" in [m["id"] for m in second["mails"]]


def test_un_seul_appel_powershell_pour_trente_jours_manquants():
    """Cache vide sur 30 jours : UN appel, pas 30 authentifications Graph."""
    runner = _RunnerGraph(mails=[MAIL_AUJOURDHUI, MAIL_J1, MAIL_J3])
    _transport(runner).mail_brut("2026-08-26T10:00:00Z")
    assert len(runner.appels) == 1


def test_chat_a_cheval_sur_deux_jours():
    """Un chat dont les messages couvrent deux jours revient en UN conteneur."""
    chat = {
        "id": "19:chat1",
        "topic": "Projet",
        "kind": "group",
        "messages": [
            {"id": "x2", "created": "2026-09-24T09:00:00Z", "sender": "bob", "body": "hier"},
            {"id": "x1", "created": "2026-09-23T09:00:00Z", "sender": "alice", "body": "avant-hier"},
        ],
    }
    runner = _RunnerGraph(chats=[chat])
    _transport(runner).chats_brut("2026-09-18T10:00:00Z")

    second = _transport(runner).chats_brut("2026-09-18T10:00:00Z")
    assert len(second["chats"]) == 1
    rendu = second["chats"][0]
    assert rendu["id"] == "19:chat1"
    assert rendu["topic"] == "Projet"
    assert [m["id"] for m in rendu["messages"]] == ["x2", "x1"]


def test_has_more_ne_fige_rien():
    """Une reponse plafonnee (`has_more`) est peut-etre tronquee : rien n'est ecrit,
    la lecture suivante redemande la fenetre entiere."""
    runner = _RunnerGraph(mails=[MAIL_AUJOURDHUI, MAIL_J1, MAIL_J3], has_more=True)
    _transport(runner).mail_brut("2026-09-18T10:00:00Z")
    _transport(runner).mail_brut("2026-09-18T10:00:00Z")
    assert _since(runner.appels[1]) == _since(runner.appels[0])


def test_canal_sans_message_conserve():
    """Regle du script : un canal calme reste listable (« voici tes canaux »)."""
    canal = {"id": "t1/c1", "equipe": "Equipe", "canal": "General", "messages": []}
    runner = _RunnerGraph(canaux=[canal])
    _transport(runner).canaux_brut("2026-09-18T10:00:00Z")

    second = _transport(runner).canaux_brut("2026-09-18T10:00:00Z")
    assert [c["id"] for c in second["canaux"]] == ["t1/c1"]


@pytest.mark.parametrize("action", ["equipes_ids", "messages", "mail_un"])
def test_actions_non_cachables_appellent_toujours_powershell(action):
    """Sans fenetre de temps, pas de tranche de jour : ces lectures ne sont pas cachees."""
    runner = _RunnerGraph()
    transport = _transport(runner)
    if action == "equipes_ids":
        transport.equipes_ids("2026-09-18T10:00:00Z")
        transport.equipes_ids("2026-09-18T10:00:00Z")
    elif action == "messages":
        transport.messages("19:chat1", depuis_iso="2026-09-18T10:00:00Z")
        transport.messages("19:chat1", depuis_iso="2026-09-18T10:00:00Z")
    else:
        transport.mail_un("m-j3")
        transport.mail_un("m-j3")
    assert len(runner.appels) == 2
