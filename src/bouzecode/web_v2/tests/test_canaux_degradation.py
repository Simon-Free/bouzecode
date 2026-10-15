"""Lister ses canaux d'equipe ne demande PAS le droit de lire leurs messages.

Constat du 2026-09-13 : l'action `canaux` ouvrait la session Graph avec le seul scope
`ChannelMessage.Read.All` (consentement administrateur). Sans ce consentement, l'humain
n'obtenait RIEN — pas meme la liste des canaux dont il est membre, alors que
`/me/joinedTeams` (Team.ReadBasic.All) et `/teams/{id}/channels`
(Channel.ReadBasic.All) sont a sa portee. Et un canal sans message dans la fenetre
disparaissait de la liste. Ces tests figent la degradation PROGRESSIVE.
"""

from __future__ import annotations

import json

import pytest

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


def _transport(charge: dict) -> tuple:
    runner = _Runner(charge)
    return runner, ms_activite.ActiviteTransport(runner=runner)


def test_les_canaux_restent_listes_quand_leurs_messages_sont_interdits():
    """Le pire cas : consentement ChannelMessage.Read.All absent."""
    runner, transport = _transport({"value": [
        {"id": "t1/19:general", "equipe": "Direction Data", "canal": "General",
         "messages": []},
        {"id": "t1/19:projets", "equipe": "Direction Data", "canal": "Projets",
         "messages": []},
    ], "has_more": False, "messages_indisponibles": True})

    rapport = ms_activite.rapport_canaux(fenetre="30j", transport=transport)

    assert rapport["ok"] is True
    #  La liste survit : c'est tout l'objet du correctif.
    assert rapport["total"] == 2
    assert [c["canal"] for c in rapport["canaux"]] == ["General", "Projets"]
    assert rapport["messages_indisponibles"] is True
    #  Et l'avertissement nomme le droit qui manque, sans faire croire a un vide.
    assert "ChannelMessage.Read.All" in rapport["avertissement"]
    assert runner.args[:2] == ["-Action", "canaux"]


def test_un_canal_sans_message_recent_reste_dans_la_liste():
    runner, transport = _transport({"value": [
        {"id": "t1/19:general", "equipe": "Ops", "canal": "General", "messages": []},
        {"id": "t1/19:actu", "equipe": "Ops", "canal": "Actu", "messages": [
            {"id": "m1", "created": "2026-09-10T09:00:00Z", "sender": "Jacques Daniel",
             "body": "peux-tu me proposer des dates ?"}]},
    ], "has_more": False})

    rapport = ms_activite.rapport_canaux(fenetre="30j", transport=transport)

    assert rapport["total"] == 2
    assert rapport["canaux_vides"] == 1
    assert rapport["messages_indisponibles"] is False


def test_lister_les_equipes_et_leurs_canaux_est_un_appel_a_part():
    """`equipes` n'appelle aucun message : c'est le chemin sans droit special."""
    runner, transport = _transport({"value": [
        {"id": "t1", "equipe": "Direction Data", "canaux": [
            {"id": "19:general", "canal": "General", "type": "standard"},
            {"id": "19:prive", "canal": "Prive", "type": "private"},
        ]},
    ]})

    rapport = ms_activite.rapport_equipes(transport=transport)

    assert rapport["ok"] is True
    assert rapport["total"] == 1
    assert rapport["total_canaux"] == 2
    assert rapport["equipes"][0]["canaux"][1]["canal"] == "Prive"
    assert runner.args[:2] == ["-Action", "equipes"]


def test_l_outil_canaux_sait_ne_demander_que_la_liste():
    schema = next(s for s in bureau_tools.BUREAU_TOOL_SCHEMAS if s["name"] == "Canaux")
    proprietes = schema["input_schema"]["properties"]
    assert "sans_messages" in proprietes, (
        "sans le drapeau, l'assistant ne peut pas se replier sur la simple liste")
    description = (schema["description"] + json.dumps(proprietes)).lower()
    assert "liste" in description


def test_le_registre_relaie_bien_le_drapeau_au_handler(monkeypatch):
    """Le bug du 2026-09-13 : un parametre expose au schema mais jamais transmis."""
    recu: dict = {}

    def _espion(fenetre="30j", top=0, sans_messages=False):
        recu.update({"fenetre": fenetre, "top": top, "sans_messages": sans_messages})
        return {"ok": True}

    monkeypatch.setattr(bureau_tools, "canaux", _espion)
    #  Le registre est construit DANS `register()` : on intercepte l'enregistrement
    #  plutot que de fouiller le module, et on ne touche pas au registry partage.
    recueillis: list = []
    monkeypatch.setattr(bureau_tools, "register_tool", recueillis.append)
    bureau_tools.register()
    outil = next((d for d in recueillis if getattr(d, "name", "") == "Canaux"), None)
    assert outil is not None, "l'outil Canaux doit etre enregistre"

    outil.func({"fenetre": "30j", "top": 7, "sans_messages": True}, None)

    assert recu["sans_messages"] is True
    assert recu["top"] == 7
