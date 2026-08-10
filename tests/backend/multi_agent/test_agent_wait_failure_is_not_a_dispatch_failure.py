# [desc] Une ATTENTE cassée n'est PAS un dispatch raté : le retour de l'outil Agent dit que
# le TICKET EXISTE (avec son id) pour qu'un manager ne redispatche jamais un DOUBLON. [/desc]
"""Le 2026-07-27, trois dispatchs RÉUSSIS ont été rapportés « Error: HTTP Error 404 » parce
que l'URL de sondage n'existait pas. Un manager qui lit ça redispatche → tickets en double.
Seams injectés via config (`_web_dispatch`, `_web_wait_verdict`), aucun mock."""
from __future__ import annotations

import urllib.error

from bouzecode.backend.multi_agent import tools

ROUTED = {"routed": True, "ticket_id": "76ccd35a", "project_name": "demo_app",
          "project_slug": "demo-app", "typology": "coder"}


def _config(wait_verdict):
    return {"_web_dispatch": lambda body: ROUTED, "_web_wait_verdict": wait_verdict}


def _exploding_wait(exc):
    def wait_verdict(ticket_id, project_slug):
        raise exc
    return wait_verdict


def test_a_broken_wait_still_announces_that_the_ticket_exists():
    """Le sondage tombe en 404 : le manager apprend que son enfant EXISTE et tourne."""
    config = _config(_exploding_wait(
        urllib.error.HTTPError("http://x", 404, "NOT FOUND", {}, None)))

    out = tools._spawn_web_ticket_agent({"prompt": "répare la boucle"}, config)

    assert "76ccd35a" in out
    assert "LE TICKET EXISTE" in out
    assert "NE REDISPATCHE PAS" in out


def test_a_broken_wait_is_never_reported_as_a_tool_error():
    """Pas de préfixe `Error:` : il est réservé au cas « aucun enfant n'a été créé »."""
    config = _config(_exploding_wait(ConnectionRefusedError("serveur injoignable")))

    out = tools._spawn_web_ticket_agent({"prompt": "p"}, config)

    assert not out.startswith("Error:")
    assert "dispatché" in out


def test_a_broken_wait_keeps_the_turn_open_because_the_child_is_in_flight():
    """L'enfant est en vol : le tour reste ouvert, comme pour un lancement en fond."""
    config = _config(_exploding_wait(ValueError("project_slug absent")))

    tools._spawn_web_ticket_agent({"prompt": "p"}, config)

    assert config["_bg_agent_launched"] is True


def test_a_dispatch_that_created_nothing_stays_a_tool_error():
    """À l'inverse, un dispatch qui n'a RIEN créé reste une erreur d'outil franche."""
    config = {"_web_dispatch": lambda body: {"routed": False, "error": "provider absent"},
              "_web_wait_verdict": _exploding_wait(RuntimeError("jamais appelé"))}

    out = tools._spawn_web_ticket_agent({"prompt": "p"}, config)

    assert out.startswith("Error:")
    assert "aucun enfant n'a été créé" in out


def test_a_missing_slug_is_a_wait_failure_not_a_dispatch_failure():
    """Réponse serveur sans project_slug : l'URL est inconstructible, mais le ticket EXISTE."""
    routed_without_slug = {k: v for k, v in ROUTED.items() if k != "project_slug"}
    config = {"_web_dispatch": lambda body: routed_without_slug}

    out = tools._spawn_web_ticket_agent({"prompt": "p"}, config)

    assert not out.startswith("Error:")
    assert "76ccd35a" in out
    assert "LE TICKET EXISTE" in out


def test_background_mode_is_untouched_by_all_this():
    """`background=true` rend la main tout de suite et n'attend jamais l'enfant."""
    config = _config(_exploding_wait(RuntimeError("l'attente ne doit pas tourner")))

    out = tools._spawn_web_ticket_agent({"prompt": "p", "background": True}, config)

    assert "EN FOND" in out
    assert config["_bg_agent_launched"] is True
