"""Les CANAUX d'equipe Teams : le trou ou une demande pouvait disparaitre en silence.

Mesure du 2026-09-13 sur la conversation `d7c83ee6` : l'assistant du Bureau avait bien lu
mails et chats, mais aucun script du depot ne touchait `/teams/{id}/channels/{id}/messages`.
Une tache donnee dans un canal d'equipe etait donc STRUCTURELLEMENT invisible : ce n'etait
pas un oubli du modele, c'etait une absence de code.
"""
from __future__ import annotations

import json

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


def _canal(identifiant: str, equipe: str, canal: str, messages: list[dict]) -> dict:
    return {"id": identifiant, "equipe": equipe, "canal": canal, "messages": messages}


def test_les_canaux_d_equipe_sont_lus_et_leurs_messages_rendus():
    """Le cas reel : « propose-moi des dates » poste dans un canal, jamais remonte."""
    runner = _Runner({"value": [
        _canal("19:aaa", "Data", "General", [
            {"id": "m1", "created": "2026-09-08T09:00:00Z", "sender": "Jacques Daniel",
             "body": "<p>Peux-tu me proposer des dates ?</p>"}]),
        _canal("19:bbb", "Data", "Projets", [
            {"id": "m2", "created": "2026-09-07T09:00:00Z", "sender": "bouzecode",
             "body": "<p>ok pour moi</p>"}]),
    ], "has_more": False})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_canaux(fenetre="30j", top=30, transport=transport)

    assert rapport["ok"] is True
    assert rapport["total"] == 2
    premier = rapport["canaux"][0]
    assert premier["equipe"] == "Data" and premier["canal"] == "General"
    assert "dates" in premier["messages"][0]["body"]
    assert premier["messages"][0]["sender"] == "Jacques Daniel"
    #  L'action part bien au script, avec une borne ISO UTC decidee par l'appelant.
    assert runner.args[:2] == ["-Action", "canaux"]
    borne = runner.args[runner.args.index("-Since") + 1]
    assert borne.endswith("Z") and borne[4] == "-"


def test_le_rapport_canaux_ne_crie_pas_a_la_troncature_quand_tout_tient():
    runner = _Runner({"value": [
        _canal("19:aaa", "Data", "General", [
            {"id": "m1", "created": "2026-09-08T09:00:00Z", "sender": "bouzecode",
             "body": "ok"}]),
    ], "has_more": False})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_canaux(fenetre="7j", top=30, transport=transport)

    assert rapport["tronque"] is False
    assert rapport["avertissement"] == ""
    assert rapport["messages_omis_total"] == 0
    assert rapport["canaux_vides"] == 0


def test_le_rapport_canaux_annonce_la_coupe_et_le_levier():
    """Meme contrat que mails et chats : une coupe se DIT, avec quoi faire ensuite."""
    runner = _Runner({"value": [
        _canal(f"19:{n}", "Data", f"Canal {n}", [
            {"id": f"m{n}", "created": "2026-09-08T09:00:00Z", "sender": "bouzecode",
             "body": "ok"}]) for n in range(3)
    ], "has_more": True})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_canaux(fenetre="30j", top=3, transport=transport)

    assert rapport["tronque"] is True
    assert rapport["plafond"] == 3
    #  L'avertissement doit nommer le levier, sinon il informe sans permettre d'agir.
    assert "top" in rapport["avertissement"]
    assert "INCOMPLETE" in rapport["avertissement"]


def test_une_coupe_de_messages_de_canal_est_annoncee_par_canal_et_en_total():
    """Le budget global s'applique aussi aux canaux : ce qu'il rogne doit se compter."""
    corps = "<p>" + ("mot " * 200) + "</p>"
    runner = _Runner({"value": [
        _canal("19:aaa", "Data", "Bruyant", [
            {"id": f"m{n}", "created": "2026-09-0%dT09:00:00Z" % ((n % 9) + 1),
             "sender": "bouzecode", "body": corps} for n in range(20)]),
    ], "has_more": False})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_canaux(fenetre="30j", top=30, transport=transport,
                                         budget=2_000)

    garde = rapport["canaux"][0]["messages"]
    assert len(garde) < 20
    assert rapport["canaux"][0]["messages_omis"] == 20 - len(garde)
    assert rapport["messages_omis_total"] == 20 - len(garde)
    assert rapport["tronque"] is True
