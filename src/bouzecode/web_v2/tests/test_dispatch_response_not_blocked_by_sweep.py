# [desc] POST /api/dispatch répond sans attendre le ménage du warm-pool. [/desc]
"""L'utilisateur qui envoie un prompt attend la confirmation, pas le ménage du parc.

`sweep_warm_pool()` est de l'entretien : il évince des process idle en trop et n'apporte RIEN
au lancement demandé. Il coûtait pourtant sa durée à CHAQUE dispatch, en tête à tête avec la
réponse HTTP. Mesuré le 2026-08-03 sur le parc réel (324 agents, 264 sessions) : ses deux
briques, `runner.list_agents()` et `store.list_agent_sessions()`, prennent 13,6 s et 14,6 s
quand le cache disque est froid — et 7,3 s ont été observées au navigateur sur un POST
/api/dispatch réel, avant que la moindre trace du nouvel agent n'apparaisse à l'écran.

Le ménage garde son moment causal (un dispatch ajoute un process au parc) mais part en fond :
la réponse ne l'attend plus.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.routes.work import fleet as fleet_routes
from bouzecode.web_v2.services.work import dispatch, fleet, projects

SLUG = "projet-test"
ATTENTE_MENAGE = 2.0


@pytest.fixture()
def projet(tmp_path):
    path = tmp_path / "projet_test"
    path.mkdir()
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(
        json.dumps([{"slug": SLUG, "name": "projet_test", "path": str(path)}]),
        encoding="utf-8")
    return path


@pytest.fixture()
def client(projet):
    with create_app().test_client() as flask_client:
        yield flask_client


@pytest.fixture(autouse=True)
def sans_lancement(monkeypatch):
    """Le ticket est créé pour de vrai ; seul le spawn du process est neutralisé.

    `require_api_sanity` refuse 503 tout dispatch quand l'env API est absent (le cas sous
    pytest) : sans ce contournement la route ne serait jamais atteinte."""
    class _Spawned:
        agent_id = "enfant-1"

    monkeypatch.setattr(dispatch, "_launch", lambda *_, **__: _Spawned())
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)


@pytest.fixture()
def menage_lent(monkeypatch):
    """Un ménage volontairement lent, qui note quand il part et quand il finit."""
    fini = threading.Event()
    parti = threading.Event()

    def _lent():
        parti.set()
        time.sleep(ATTENTE_MENAGE)
        fini.set()
        return []

    monkeypatch.setattr(fleet, "sweep_warm_pool", _lent)
    monkeypatch.setattr(fleet_routes.fleet, "sweep_warm_pool", _lent)
    return parti, fini


def test_la_reponse_au_prompt_n_attend_pas_le_menage_du_parc(client, menage_lent):
    """Un ménage de 2 s ne retarde pas d'autant la confirmation du dispatch."""
    parti, fini = menage_lent

    debut = time.perf_counter()
    resp = client.post("/api/dispatch", json={
        "prompt": "réponds PONG", "project_slug": SLUG, "defer": True,
    })
    duree = time.perf_counter() - debut

    assert resp.status_code == 200
    assert resp.get_json().get("ticket_id")
    assert duree < ATTENTE_MENAGE / 2, (
        f"la réponse a attendu le ménage ({duree:.2f}s pour un ménage de {ATTENTE_MENAGE}s)")
    assert not fini.is_set(), "le ménage était terminé : il a donc tourné dans la requête"


def test_le_menage_du_parc_a_bien_lieu_apres_la_reponse(client, menage_lent):
    """Déporté en fond n'est pas abandonné : le ménage tourne quand même."""
    parti, fini = menage_lent

    client.post("/api/dispatch", json={
        "prompt": "réponds PONG", "project_slug": SLUG, "defer": True,
    })

    assert parti.wait(timeout=5.0), "le ménage n'a jamais démarré"
    assert fini.wait(timeout=5.0), "le ménage n'est jamais allé au bout"
