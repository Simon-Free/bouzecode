"""Outil `Agenda` de l'assistant : lecture de l'agenda Outlook, sans aucun appel Graph reel.

Le faux `powershell` se comporte comme l'action `agenda` de `graph_activite.ps1` : il
filtre son stock sur [-Since, -Until], plafonne a -Top et COMPTE ses appels.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from bouzecode.backend.tools.bureau_agenda import agenda
from bouzecode.web_v2.services.work.ms_activite import ActiviteTransport

MAINTENANT = datetime(2026, 10, 5, 9, 0, 0, tzinfo=timezone.utc)

HIER = {"id": "e-hier", "subject": "Comite", "start": "2026-10-04T14:00:00Z",
        "end": "2026-10-04T15:00:00Z", "organizer": "Alice", "cancelled": False}
CE_MATIN = {"id": "e-matin", "subject": "Point equipe", "start": "2026-10-05T07:30:00Z",
            "end": "2026-10-05T08:00:00Z", "join_url": "https://teams/1"}
DEMAIN = {"id": "e-demain", "subject": "Revue sprint", "start": "2026-10-06T10:00:00Z",
          "end": "2026-10-06T11:00:00Z", "cancelled": True}


class _RunnerAgenda:
    def __init__(self, evenements):
        self.evenements = list(evenements)
        self.appels: list[dict] = []

    def __call__(self, args):
        args = list(args)
        params = {str(args[i])[1:]: args[i + 1] for i in range(0, len(args) - 1)
                  if str(args[i]).startswith("-")}
        self.appels.append(params)
        assert params.get("Action") == "agenda"
        gardes = [e for e in self.evenements
                  if params["Since"] <= e["start"] <= params["Until"]]
        top = int(params.get("Top") or 50)
        return 0, json.dumps({"value": gardes[:top], "has_more": len(gardes) > top}), ""


@pytest.fixture(autouse=True)
def _cache_jetable(tmp_path, monkeypatch):
    monkeypatch.setenv("BOUZECODE_MS_ACTIVITE_CACHE_DIR", str(tmp_path / "cache"))


def _transport(runner):
    return ActiviteTransport(runner=runner, maintenant=MAINTENANT)


def test_a_venir_part_de_ce_matin_et_rend_les_evenements_dans_l_ordre():
    runner = _RunnerAgenda([DEMAIN, HIER, CE_MATIN])
    rendu = agenda("2j", "a_venir", transport=_transport(runner), maintenant=MAINTENANT)

    assert rendu["ok"] and not rendu["tronque"]
    assert rendu["debut"] == "2026-10-05T00:00:00Z"
    assert rendu["fin"] == "2026-10-07T09:00:00Z"
    assert [e["id"] for e in rendu["evenements"]] == ["e-matin", "e-demain"]
    assert rendu["evenements"][1]["annule"] is True
    assert runner.appels[0]["Until"] == "2026-10-07T09:00:00Z"


def test_passe_fige_les_jours_revolus_et_ne_relit_que_le_jour_courant():
    runner = _RunnerAgenda([HIER, CE_MATIN])
    premier = agenda("2j", "passe", transport=_transport(runner), maintenant=MAINTENANT)
    second = agenda("2j", "passe", transport=_transport(runner), maintenant=MAINTENANT)

    assert [e["id"] for e in premier["evenements"]] == ["e-hier", "e-matin"]
    assert [e["id"] for e in second["evenements"]] == ["e-hier", "e-matin"]
    assert runner.appels[1]["Since"] == "2026-10-05T00:00:00Z"


def test_plafond_atteint_le_dit():
    runner = _RunnerAgenda([CE_MATIN, DEMAIN])
    rendu = agenda("7j", "a_venir", top=1, transport=_transport(runner), maintenant=MAINTENANT)

    assert rendu["tronque"] is True
    assert "COUVERTURE INCOMPLETE" in rendu["avertissement"]


def test_fenetre_inconnue_est_refusee_sans_appel():
    runner = _RunnerAgenda([CE_MATIN])
    rendu = agenda("1 mois", transport=_transport(runner), maintenant=MAINTENANT)

    assert rendu == {"ok": False, "erreur": "fenetre_invalide",
                     "message": rendu["message"]}
    assert runner.appels == []


def test_refus_de_consentement_est_une_reponse():
    def refus(_args):
        return 1, json.dumps({"error": {"code": "AuthenticationError",
                                        "message": "Forbidden", "action": "agenda"}}), ""
    rendu = agenda("7j", transport=_transport(refus), maintenant=MAINTENANT)

    assert rendu["ok"] is False and rendu["erreur"] == "authentification"
    assert "Calendars.Read" in rendu["consigne"]
