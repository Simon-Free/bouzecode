# [desc] BUG 1 : l'outil Agent (mode web) poste /api/dispatch avec un timeout GÉNÉREUX et
# defer=True, et gère une réponse sans 'key' (mode déféré). Prouve qu'un dispatch qui prend
# du temps ne provoque plus de faux timeout → pas de tickets dupliqués.
# Espion sur `core.local_http.local_json` (le client local sanctionné), zéro réseau. [/desc]
from __future__ import annotations

from bouzecode.backend.core import local_http
from bouzecode.backend.multi_agent import tools


def _patch_local_json(monkeypatch, payload: dict, captured: dict):
    """Espionne le SEUL client HTTP local sanctionné (`core.local_http.local_json`),
    c'est-à-dire le seam que `_default_web_dispatch` traverse RÉELLEMENT. Espionner
    `urllib.request.urlopen` n'intercepterait plus rien : le dispatch local n'utilise
    volontairement plus l'opener par défaut (il partait dans le proxy → 407)."""
    def fake_local_json(method, url, body=None, timeout=60):
        captured.update(method=method, url=url, body=body, timeout=timeout)
        return payload

    monkeypatch.setattr(local_http, "local_json", fake_local_json)


def _wait_stub() -> dict:
    """Config qui neutralise l'ATTENTE de l'enfant : ces tests portent sur le POST de
    dispatch, pas sur le sondage du ticket (couvert par test_agent_wait_for_child.py)."""
    return {"_web_wait_verdict": lambda ticket_id, project_slug: "VERDICT: OK"}


def test_dispatch_uses_generous_timeout_and_requests_defer(monkeypatch):
    captured: dict = {}
    _patch_local_json(monkeypatch, {
        "routed": True, "ticket_id": "t1", "project_name": "P",
        "typology": "coder", "deferred": True,
    }, captured)
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr123.ipc")

    out = tools._spawn_web_ticket_agent(
        {"prompt": "code X", "subagent_type": "coder"}, _wait_stub())

    # timeout large : bien au-delà des 30 s qui causaient le faux timeout + doublon
    assert captured["timeout"] >= 120
    # le corps demande le mode déféré (réponse rapide côté serveur)
    assert captured["body"]["defer"] is True
    assert captured["body"]["parent"] == "mgr123"
    assert "t1" in out


def test_handles_response_without_key(monkeypatch):
    # En mode déféré la réponse n'a PAS de 'key' : l'outil ne doit pas planter (KeyError).
    captured: dict = {}
    _patch_local_json(monkeypatch, {
        "routed": True, "ticket_id": "abcd1234", "project_name": "P",
        "typology": "coder", "deferred": True,
    }, captured)
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr999.ipc")

    out = tools._spawn_web_ticket_agent({"prompt": "code Y"}, _wait_stub())

    assert "abcd1234" in out
    assert "ré-invoqué" in out.lower() or "reinvoque" in out.lower() or "verdict" in out.lower()


def test_needs_project_message(monkeypatch):
    captured: dict = {}
    _patch_local_json(monkeypatch, {"needs_project": True}, captured)
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr.ipc")

    out = tools._spawn_web_ticket_agent({"prompt": "?"}, _wait_stub())

    assert "aucun projet" in out.lower()
