# [desc] Câblage des primitives d'orchestration : l'outil Agent expose resume_branch,
# MessageAgent est enregistré + whitelisté par le profil manager, et poste bien
# resume_branch dans le body de dispatch. Zéro réseau, zéro agent LLM. [/desc]
from __future__ import annotations

from bouzecode.backend.core import local_http
from bouzecode.backend.core.tool_registry import _registry
from bouzecode.backend.multi_agent import lancement_web, outils_enfants
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
    # Hors mode bouzeui web : message clair, aucun POST réseau tenté.
    from bouzecode.backend.tools import interaction
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: False)

    out = outils_enfants._message_agent({"ticket_id": "t1", "text": "hop"}, {})

    assert "web" in out.lower()


#  Les enfants du parent tels que les rend GET /api/agents/<moi>/children (seam de l'outil).
_ENFANTS = {"_web_children": lambda: {"children": [{"ticket_id": "abc123", "slug": "p"}]}}


def _spy_local_json(monkeypatch, payload: dict, captured: dict):
    """Espionne `core.local_http.local_json` — le SEUL client HTTP local sanctionné, et donc
    le seam réellement traversé. Un espion sur `urllib.request.urlopen` n'intercepterait plus
    rien : les appels locaux n'utilisent volontairement plus l'opener par défaut (il les
    faisait partir dans le proxy d'entreprise → 407)."""
    def fake_local_json(method, url, body=None, timeout=60, headers=None):
        if method == "GET" and "/api/agents/" in url:  # fiche du parent : son projet
            return {"project_slug": "p"}
        captured.update(url=url, body=body, headers=headers)
        return payload

    monkeypatch.setattr(local_http, "local_json", fake_local_json)


def test_message_agent_posts_to_message_endpoint(monkeypatch):
    from bouzecode.backend.tools import interaction
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: True)
    captured: dict = {}
    _spy_local_json(monkeypatch, {"ok": True}, captured)

    out = outils_enfants._message_agent({"ticket_id": "abc123", "text": "réoriente"}, _ENFANTS)

    assert captured["url"].endswith("/api/projects/p/tickets/abc123/messages")
    assert captured["body"] == {"text": "réoriente", "mode": "queue", "arreter": False,
                                "origine": "parent"}
    assert "abc123" in out


def test_message_agent_refuse_un_ticket_qui_n_est_pas_un_enfant(monkeypatch):
    from bouzecode.backend.tools import interaction
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: True)
    captured: dict = {}
    _spy_local_json(monkeypatch, {"ok": True}, captured)

    out = outils_enfants._message_agent({"ticket_id": "inconnu", "text": "hop"}, _ENFANTS)

    assert "NON transmis" in out and captured == {}


def test_message_agent_peut_interrompre_un_enfant_en_plein_tour(monkeypatch):
    """`interrompre` part au serveur ; la réponse dit à l'appelant QUAND l'enfant le lira."""
    from bouzecode.backend.tools import interaction
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: True)
    captured: dict = {}
    _spy_local_json(monkeypatch, {"ok": True, "queued": True, "en_tour": True}, captured)

    out = outils_enfants._message_agent({"ticket_id": "abc123", "text": "stop, autre piste",
                                "interrompre": True}, _ENFANTS)

    assert captured["body"]["mode"] == "now"
    assert "coupé" in out, out


def test_spawn_web_ticket_forwards_resume_branch(monkeypatch):
    captured: dict = {}
    _spy_local_json(monkeypatch, {"routed": True, "ticket_id": "t1", "project_name": "P",
                                  "typology": "coder", "deferred": True}, captured)
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr.ipc")

    lancement_web._spawn_web_ticket_agent(
        {"prompt": "reprends", "resume_branch": "agent/old"},
        # L'attente de l'enfant est neutralisée : ce test porte sur le corps du dispatch.
        {"_web_wait_verdict": lambda ticket_id, project_slug: "VERDICT: OK"})

    assert captured["body"]["resume_branch"] == "agent/old"
    assert captured["url"].endswith("/api/projects/p/tickets")
    assert captured["body"]["parent"]["agent_id"] == "mgr"
    assert captured["headers"]["Idempotency-Key"]
