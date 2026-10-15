"""Timeouts Graph des outils Bureau `Mails` et `Teams` (constat du 2026-10-15).

Mails ET Teams pendaient 120 s dans Connect-MgGraph (login interactif impossible sous
-NonInteractive) avant toute requete Graph ; l'erreur disait seulement « Teams (mail)
n'a pas repondu en 90s ». Le faux runner joue le contrat du vrai script : il emet les
memes marqueurs stderr `BZ_ETAPE:` et leve le meme `subprocess.TimeoutExpired`.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import ms_activite
from bouzecode.web_v2.services.work.teams.graph_transport import derniere_etape


def _transport(runner, timeout=None):
    return ms_activite.ActiviteTransport(runner=runner, timeout=timeout, cache=False)


class _RunnerPendu:
    """Le process PowerShell depasse son delai apres avoir annonce `etapes`."""

    def __init__(self, *etapes: str):
        self.stderr = "".join(f"BZ_ETAPE: {e}\n" for e in etapes).encode("utf-8")
        self.appels: list[list[str]] = []

    def __call__(self, args):
        self.appels.append(list(args))
        raise subprocess.TimeoutExpired(cmd=["powershell"], timeout=1, stderr=self.stderr)


def _mail(rang: int) -> dict:
    recu = (datetime.now(timezone.utc) - timedelta(hours=rang + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": f"m{rang}", "subject": f"Sujet {rang}", "received": recu,
            "sender": "a@b.c", "preview": "apercu", "web_link": "", "is_read": False}


class _RunnerMails:
    def __init__(self, nombre: int, has_more: bool):
        self.nombre = nombre
        self.has_more = has_more

    def __call__(self, args):
        params = dict(zip(args[::2], args[1::2]))
        top = int(params.get("-Top", 50))
        mails = [_mail(r) for r in range(min(self.nombre, top))]
        return 0, json.dumps({"value": mails, "has_more": self.has_more}), ""


def test_derniere_etape_lit_le_dernier_marqueur_stderr_partiel():
    stderr = b"GRAPH_APP_PARTAGEE: ...\nBZ_ETAPE: connexion scopes=Mail.Read\nBZ_ETAPE: GET https://x/me\n"
    assert derniere_etape(stderr) == "GET https://x/me"
    assert derniere_etape(None) == ""


def test_mails_pendu_a_la_connexion_dit_reconnexion_interactive():
    runner = _RunnerPendu("connexion scopes=Mail.Read")
    retour = bureau_tools.mails(fenetre="2j", top=15, transport=_transport(runner))
    assert retour["ok"] is False and retour["erreur"] == "transport"
    assert "connexion scopes=Mail.Read" in retour["message"]
    assert "reconnexion" in retour["message"]
    assert "aucune requete Graph" in retour["message"]
    assert "consigne" in retour


def test_mails_pendu_sur_une_requete_nomme_la_requete_get():
    uri = "https://graph.microsoft.com/v1.0/me/mailFolders('inbox')/messages?$top=15"
    runner = _RunnerPendu("connexion scopes=Mail.Read", f"GET {uri}")
    retour = bureau_tools.mails(fenetre="2j", top=15, transport=_transport(runner))
    assert retour["erreur"] == "transport"
    assert f"GET {uri}" in retour["message"]
    assert "reconnexion" not in retour["message"]


def test_mails_param_timeout_pris_en_compte():
    runner = _RunnerPendu("GET https://x")
    retour = bureau_tools.mails(fenetre="2j", transport=_transport(runner, timeout=7))
    assert "en 7s" in retour["message"]
    #  Sans transport injecte, le pont est construit avec ce timeout.
    assert "timeout" in bureau_tools.mails.__code__.co_varnames
    schema = next(s for s in bureau_tools.BUREAU_TOOL_SCHEMAS if s["name"] == "Mails")
    assert "timeout" in schema["input_schema"]["properties"]


def test_mails_tronque_quand_graph_annonce_une_suite():
    retour = bureau_tools.mails(fenetre="2j", top=5,
                                transport=_transport(_RunnerMails(20, has_more=True)))
    assert retour.get("tronque") is True
    assert len(retour["mails"]) == 5


def test_mails_non_tronque_sous_le_plafond():
    retour = bureau_tools.mails(fenetre="2j", top=10,
                                transport=_transport(_RunnerMails(3, has_more=False)))
    assert retour.get("tronque") is False
    assert len(retour["mails"]) == 3


def test_listener_msal_devient_erreur_authentification():
    def runner(args):
        charge = {"error": {"code": "PowerShellFailure",
                            "message": "Une erreur s'est produite lors de l'écriture dans un écouteur."}}
        return 1, json.dumps(charge), "GRAPH_APP_PARTAGEE: ..."

    retour = bureau_tools.mails(fenetre="2j", transport=_transport(runner))
    assert retour["erreur"] == "authentification"


def test_teams_pendu_a_la_connexion_dit_reconnexion_interactive():
    runner = _RunnerPendu("connexion scopes=Chat.Read")
    retour = bureau_tools.teams(fenetre="30j", transport=_transport(runner))
    assert retour["ok"] is False
    assert "reconnexion" in retour["message"]
