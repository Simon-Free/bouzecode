"""Le dispatch d'un manager porte un projet, et son ÉCHEC se voit comme une erreur.

Le corps envoyé au serveur porte toujours la clé `project_slug` : vide, le serveur la
déduit du parent (héritage) ; renseignée, elle prime. Et un dispatch refusé revient en
ERREUR d'outil — jamais en compte rendu neutre, qu'un manager relisait comme un succès
avant d'annoncer « ticket dispatché » alors qu'aucun enfant n'existait.
"""
from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.multi_agent import tools


def _config(monkeypatch, response):
    """Injecte le seam de dispatch : capture le corps posté, renvoie `response`."""
    sent: list[dict] = []

    def fake_dispatch(body):
        sent.append(body)
        return response

    def fake_wait(ticket_id, project_slug):
        return "VERDICT: OK"

    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/9d0789f2fdca.ipc")
    return {"_web_dispatch": fake_dispatch, "_web_wait_verdict": fake_wait}, sent


_ROUTED = {"routed": True, "ticket_id": "t1", "project_name": "demo_app",
           "typology": "coder"}


def test_a_dispatch_leaves_the_project_to_be_inherited_by_default(monkeypatch):
    """Sans projet nommé, le corps porte un project_slug VIDE : le serveur l'hérite du parent."""
    config, sent = _config(monkeypatch, _ROUTED)

    tools._spawn_web_ticket_agent({"prompt": "répare la boucle", "background": True}, config)

    assert sent[0]["project_slug"] == ""
    assert sent[0]["parent"] == "9d0789f2fdca"


def test_an_explicit_project_slug_is_forwarded_to_the_server(monkeypatch):
    """Le projet nommé par le manager part tel quel dans le corps du dispatch."""
    config, sent = _config(monkeypatch, _ROUTED)

    tools._spawn_web_ticket_agent(
        {"prompt": "ingère", "project_slug": "demo-ingestion", "background": True}, config)

    assert sent[0]["project_slug"] == "demo-ingestion"


def test_a_dispatch_refused_for_lack_of_project_is_an_error(monkeypatch):
    """Un dispatch refusé faute de projet revient en ERREUR, et liste les projets valides."""
    config, _ = _config(monkeypatch, {
        "needs_project": True, "routed": False,
        "suggestions": [{"slug": "demo-app", "name": "demo_app"}],
    })

    out = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert out.startswith("Error:")
    assert "demo-app" in out
    assert config.get("_bg_agent_launched") is not True


def test_a_dispatch_that_did_not_route_is_an_error(monkeypatch):
    """Un dispatch qui n'a routé nulle part revient en ERREUR, pas en compte rendu neutre."""
    config, _ = _config(monkeypatch, {"routed": False, "error": "provider absent"})

    out = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert out.startswith("Error:")
    assert "provider absent" in out
    assert config.get("_bg_agent_launched") is not True


def test_a_successful_dispatch_is_not_reported_as_an_error(monkeypatch):
    """Le succès reste un compte rendu lisible et arme le drapeau d'enfant en vol."""
    config, _ = _config(monkeypatch, _ROUTED)

    out = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert not out.startswith("Error:")
    assert "t1" in out
    assert config["_bg_agent_launched"] is True


def test_the_agent_tool_offers_project_slug_as_a_parameter():
    """Le conseil « précise project_slug » est applicable : le paramètre existe au contrat."""
    properties = get_tool("Agent").schema["input_schema"]["properties"]

    assert "project_slug" in properties
