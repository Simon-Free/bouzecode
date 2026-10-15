"""Acces A LA DEMANDE au contenu complet des messages Teams.

La reduction de volume (`_alleger`) coupe les corps a 400 caracteres et ne garde que
quelques messages par conversation. Ces tests verifient que l'assistant peut ALLER
CHERCHER ce qui a ete coupe : une information tronquee sans moyen de la recuperer est
une information perdue.

Aucun PowerShell, aucun tenant : le transport recoit un faux runner.
"""

from __future__ import annotations

import inspect
import json

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import ms_activite


class _Runner:
    """Faux `powershell` : memorise les arguments, rend un JSON fixe."""

    def __init__(self, charge: dict, code: int = 0):
        self.charge = charge
        self.code = code
        self.args: list[str] = []

    def __call__(self, args):
        self.args = list(args)
        return self.code, json.dumps(self.charge), ""


def _message(body: str, ident: str = "m1") -> dict:
    return {"id": ident, "created": "2026-09-08T09:00:00Z", "sender": "bouzecode", "body": body}


def test_le_detail_dune_conversation_demande_laction_messages():
    """Sans la bonne action, le script PowerShell ne sait pas quoi aller chercher."""
    runner = _Runner({"value": [_message("<p>ok</p>")]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    ms_activite.messages_conversation("19:abc@thread.v2", fenetre="30j",
                                      transport=transport)

    assert "-Action" in runner.args
    assert runner.args[runner.args.index("-Action") + 1] == "messages"
    assert "-ChatId" in runner.args
    assert runner.args[runner.args.index("-ChatId") + 1] == "19:abc@thread.v2"


def test_le_detail_garde_un_corps_long_non_tronque_a_400():
    """Le mode detail n'a d'interet que s'il rend PLUS que la liste allegee."""
    long_corps = "<p>" + ("mot " * 300) + "</p>"
    runner = _Runner({"value": [_message(long_corps)]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    messages = ms_activite.messages_conversation("19:abc", fenetre="30j",
                                                 transport=transport)

    corps = messages[0]["body"]
    assert len(corps) > ms_activite.BODY_MAX * 2
    assert len(corps) <= ms_activite.BODY_DETAIL + 1


def test_un_message_precis_est_rendu_en_entier():
    """« Contenu complet » veut dire complet : aucun plafond sur un message nomme."""
    enorme = "<p>" + ("z" * 20_000) + "</p>"
    runner = _Runner({"value": [_message(enorme, ident="m42")]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    messages = ms_activite.messages_conversation("19:abc", fenetre="30j",
                                                 message_id="m42",
                                                 transport=transport)

    assert len(messages[0]["body"]) >= 20_000
    assert "-MessageId" in runner.args
    assert runner.args[runner.args.index("-MessageId") + 1] == "m42"


def test_le_detail_reste_du_texte_et_jamais_du_html():
    """L'assistant lit du texte : « complet » ne veut pas dire « avec les balises »."""
    runner = _Runner({"value": [_message("<div><p>bonjour&nbsp;Jean</p></div>")]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    messages = ms_activite.messages_conversation("19:abc", fenetre="30j",
                                                 transport=transport)

    corps = messages[0]["body"]
    assert "<" not in corps
    assert "&nbsp;" not in corps
    assert "bonjour" in corps and "Jean" in corps


def test_le_tool_teams_accepte_conversation_id_et_message_id():
    """Un parametre absent du schema ou jete par le lambda est inutilisable."""
    parametres = inspect.signature(bureau_tools.teams).parameters
    assert "conversation_id" in parametres
    assert "message_id" in parametres

    schema = {s["name"]: s for s in bureau_tools.BUREAU_TOOL_SCHEMAS}["Teams"]
    proprietes = schema["input_schema"]["properties"]
    assert "conversation_id" in proprietes
    assert "message_id" in proprietes
