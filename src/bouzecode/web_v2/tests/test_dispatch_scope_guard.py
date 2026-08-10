# [desc] POST /api/dispatch signale un ticket en doublon de périmètre et un mandat read-only non tenu. [/desc]
"""Le garde-fou de périmètre est branché sur la VRAIE voie de dispatch du manager.

Le détail des détections est couvert par `test_scope_guard.py` ; ici on vérifie qu'elles
sont effectivement appelées par `POST /api/dispatch`, que le drapeau atterrit sur le ticket
(donc visible en UI et interrogeable) et que l'avertissement remonte dans la réponse — le
manager est le seul acteur capable de corriger son découpage.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services import scope_guard
from bouzecode.web_v2.services.work import dispatch, projects, tickets
from bouzecode.web_v2.tests.scope_guard_prompts import (
    DIRECTE_B, DIRECTE_ECRIVAIN, INDIRECTE_BLOQUANTE, INDIRECTE_TICKET_A,
)

SLUG = "demo-app"
MANAGER_ID = "aabbccddeeff"


@pytest.fixture()
def projet(tmp_path):
    path = tmp_path / "demo_app"
    path.mkdir()
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(
        json.dumps([{"slug": SLUG, "name": "demo_app", "path": str(path)}]),
        encoding="utf-8")
    return path


@pytest.fixture()
def manager(tmp_path, monkeypatch, projet):
    """Un manager déjà lancé : c'est lui le `parent` de tous les tickets dispatchés."""
    agents = tmp_path / "web_agents"
    agents.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents)
    (agents / f"{MANAGER_ID}.json").write_text(json.dumps({
        "agent_id": MANAGER_ID, "prompt": "implémente les deux mesures", "model": "opus",
        "cwd": str(projet), "pid": 4242, "started_at": "2026-07-27T10:00:00",
        "ticket_slug": SLUG, "ticket_id": "ba5eba11", "parent": "dispatcher:manual",
    }), encoding="utf-8")
    return MANAGER_ID


@pytest.fixture(autouse=True)
def sans_lancement(monkeypatch):
    """Le dispatch crée le ticket pour de vrai ; seul le spawn du process est neutralisé."""
    class _Spawned:
        agent_id = "enfant-1"

    monkeypatch.setattr(dispatch, "_launch", lambda *_, **__: _Spawned())


def _dispatcher(prompt: str, manager: str, typology: str = "coder") -> dict:
    return dispatch.dispatch(prompt, parent=manager, typology=typology)


def _relire(ticket_id: str) -> dict:
    return tickets.get_ticket(SLUG, ticket_id)


def test_le_second_ecrivain_sur_le_meme_livrable_est_drapeaute_sur_son_ticket(manager):
    premier = _dispatcher(DIRECTE_B, manager)
    second = _dispatcher(DIRECTE_ECRIVAIN, manager)

    avertissements = scope_guard.review_dispatch(
        SLUG, second["ticket_id"], DIRECTE_ECRIVAIN, "coder", manager)

    ticket = _relire(second["ticket_id"])
    assert ticket[scope_guard.OVERLAP_FLAG_KEY] == [premier["ticket_id"]]
    assert any(premier["ticket_id"] in c["text"] for c in ticket["comments"])
    assert any("DOUBLON" in a for a in avertissements)


def test_lautre_moitie_de_la_demande_passe_sans_etre_drapeautee(manager):
    _dispatcher(DIRECTE_B, manager)
    autre = _dispatcher(INDIRECTE_TICKET_A, manager, typology="general-purpose")

    scope_guard.review_dispatch(SLUG, autre["ticket_id"], INDIRECTE_TICKET_A,
                                "general-purpose", manager)

    assert scope_guard.OVERLAP_FLAG_KEY not in _relire(autre["ticket_id"])


def test_un_ticket_read_only_confie_a_coder_est_drapeaute(manager):
    ticket_id = _dispatcher(INDIRECTE_BLOQUANTE, manager)["ticket_id"]

    avertissements = scope_guard.review_dispatch(
        SLUG, ticket_id, INDIRECTE_BLOQUANTE, "coder", manager)

    ticket = _relire(ticket_id)
    assert "Write" in ticket[scope_guard.READONLY_FLAG_KEY]
    assert any("READ-ONLY" in c["text"] for c in ticket["comments"])
    assert any("READ-ONLY" in a for a in avertissements)


def test_un_premier_ticket_sans_frere_ne_declenche_rien(manager):
    ticket_id = _dispatcher(DIRECTE_B, manager)["ticket_id"]

    assert scope_guard.review_dispatch(SLUG, ticket_id, DIRECTE_B, "coder", manager) == []


@pytest.fixture()
def client_web():
    """Client de la vraie app. `require_api_sanity` refuse 503 tout dispatch sans
    environnement API joignable : on passe par le seam d'injection prévu (env + sonde),
    pas par du mock, et on rend le module à son état neuf après le test."""
    from bouzecode.web_v2 import api_sanity
    from bouzecode.web_v2.app import create_app

    client = create_app().test_client()
    api_sanity.capture_api_sanity(
        env={"ANTHROPIC_BASE_URL": "http://api.test", "ANTHROPIC_API_KEY": "test-key"},
        ping=lambda *_, **__: True, sleep=lambda *_: None)
    yield client
    api_sanity.reset_api_sanity()


def test_la_voie_api_dispatch_rend_les_avertissements_au_manager(manager, client_web):
    """Le bout en bout : c'est la réponse de `/api/dispatch` que l'outil `Agent` relit."""
    client = client_web
    corps = {"prompt": DIRECTE_B, "parent": manager, "typology": "coder"}
    assert client.post("/api/dispatch", json=corps).status_code == 200

    corps["prompt"] = DIRECTE_ECRIVAIN
    reponse = client.post("/api/dispatch", json=corps).get_json()

    assert any("DOUBLON" in a for a in reponse["scope_warnings"])
