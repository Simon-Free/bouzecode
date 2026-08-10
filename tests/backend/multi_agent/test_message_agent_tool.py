# [desc] Câblage des primitives d'orchestration : l'outil Agent expose resume_branch,
# MessageAgent est enregistré + whitelisté par le profil manager, et poste bien
# resume_branch dans le body de dispatch. Zéro réseau, zéro agent LLM. [/desc]
from __future__ import annotations

from bouzecode.backend.core import local_http
from bouzecode.backend.core.tool_registry import _registry
from bouzecode.backend.multi_agent import tools
from bouzecode.backend.profiles import resolve_agent_profile


def test_agent_def_exposes_resume_branch():
    props = _registry["Agent"].schema["input_schema"]["properties"]
    assert "resume_branch" in props
    assert props["resume_branch"]["type"] == "string"


def test_message_agent_registered_with_required_params():
    assert "MessageAgent" in _registry
    props = _registry["MessageAgent"].schema["input_schema"]["properties"]
    assert set(("ticket_id", "text")).issubset(props)
    assert _registry["MessageAgent"].schema["input_schema"]["required"] == ["ticket_id", "text"]


def test_manager_profile_whitelists_message_agent():
    profile = resolve_agent_profile("manager")
    assert "MessageAgent" in profile.tools


def test_message_agent_outside_web_ipc_is_unavailable(monkeypatch):
    # Hors mode BouzéqUI web : message clair, aucun POST réseau tenté.
    monkeypatch.setattr(tools, "is_web_ipc_active", lambda: False, raising=False)
    from bouzecode.backend.tools import interaction
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: False)

    out = tools._message_agent({"ticket_id": "t1", "text": "hop"}, {})

    assert "web" in out.lower()


def _spy_local_json(monkeypatch, payload: dict, captured: dict):
    """Espionne `core.local_http.local_json` — le SEUL client HTTP local sanctionné, et donc
    le seam réellement traversé. Un espion sur `urllib.request.urlopen` n'intercepterait plus
    rien : les appels locaux n'utilisent volontairement plus l'opener par défaut (il les
    faisait partir dans le proxy d'entreprise → 407)."""
    def fake_local_json(method, url, body=None, timeout=60):
        captured.update(url=url, body=body)
        return payload

    monkeypatch.setattr(local_http, "local_json", fake_local_json)


def test_message_agent_posts_to_message_endpoint(monkeypatch):
    from bouzecode.backend.tools import interaction
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: True)
    captured: dict = {}
    _spy_local_json(monkeypatch, {"ok": True}, captured)

    out = tools._message_agent({"ticket_id": "abc123", "text": "réoriente"}, {})

    assert captured["url"].endswith("/api/agent/message")
    assert captured["body"] == {"ticket_id": "abc123", "text": "réoriente"}
    assert "abc123" in out


def test_spawn_web_ticket_forwards_resume_branch(monkeypatch):
    captured: dict = {}
    _spy_local_json(monkeypatch, {"routed": True, "ticket_id": "t1", "project_name": "P",
                                  "typology": "coder", "deferred": True}, captured)
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr.ipc")

    tools._spawn_web_ticket_agent(
        {"prompt": "reprends", "resume_branch": "agent/old"},
        # L'attente de l'enfant est neutralisée : ce test porte sur le corps du dispatch.
        {"_web_wait_verdict": lambda ticket_id, project_slug: "VERDICT: OK"})

    assert captured["body"]["resume_branch"] == "agent/old"
