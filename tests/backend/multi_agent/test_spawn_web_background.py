"""FIX 2 — sémantique `background` alignée sur Bash au spawn de sous-agent web.

Défaut (aucun param) = PAUSE : le parent bloque jusqu'au verdict de l'enfant.
`background=True` = rend la main, le parent continue son tour.
Rétrocompat `wait` : `wait=False` → continue ; `wait=True` → pause (override).
"""
from bouzecode.backend.multi_agent import tools


def _cfg(monkeypatch, verdict="OK"):
    """Injecte _web_dispatch (fake routé) + _web_wait_verdict (compteur d'appel)."""
    calls = {"wait": 0}

    def fake_dispatch(body):
        return {"routed": True, "ticket_id": "t1", "project_name": "P",
                "typology": "coder", "project_slug": "p"}

    def fake_wait(ticket_id, project_slug):
        calls["wait"] += 1
        calls["slug"] = project_slug
        return verdict

    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr123.ipc")
    config = {"_web_dispatch": fake_dispatch, "_web_wait_verdict": fake_wait}
    return config, calls


def test_default_is_pause(monkeypatch):
    """Aucun param → PAUSE : wait_verdict appelé avec le slug du projet, verdict renvoyé."""
    config, calls = _cfg(monkeypatch)
    out = tools._spawn_web_ticket_agent({"prompt": "x"}, config)
    assert calls["wait"] == 1
    assert calls["slug"] == "p"
    assert "OK" in out
    assert config.get("_bg_agent_launched") is not True


def test_background_true_rend_la_main(monkeypatch):
    """background=True → CONTINUE : wait_verdict NON appelé, _bg_agent_launched posé."""
    config, calls = _cfg(monkeypatch)
    out = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)
    assert calls["wait"] == 0
    assert config["_bg_agent_launched"] is True
    assert "EN FOND" in out


def test_wait_false_legacy_continue(monkeypatch):
    """Rétrocompat : wait=False explicite → continue (comme background=True)."""
    config, calls = _cfg(monkeypatch)
    out = tools._spawn_web_ticket_agent({"prompt": "x", "wait": False}, config)
    assert calls["wait"] == 0
    assert config["_bg_agent_launched"] is True


def test_wait_true_explicit_pause(monkeypatch):
    """wait=True explicite → PAUSE même sémantique que le défaut."""
    config, calls = _cfg(monkeypatch)
    out = tools._spawn_web_ticket_agent({"prompt": "x", "wait": True}, config)
    assert calls["wait"] == 1
    assert "OK" in out


def test_wait_overrides_background(monkeypatch):
    """`wait` fourni prime sur `background` (rétrocompat explicite) :
    wait=True + background=True → pause (wait gagne)."""
    config, calls = _cfg(monkeypatch)
    out = tools._spawn_web_ticket_agent({"prompt": "x", "wait": True, "background": True}, config)
    assert calls["wait"] == 1
