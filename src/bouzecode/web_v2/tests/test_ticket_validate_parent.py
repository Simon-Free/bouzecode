from types import SimpleNamespace

import pytest


def _make_client(monkeypatch, ticket):
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2 import api_sanity
    from bouzecode.web_v2.routes.work import tickets as troute

    captured: dict = {}

    monkeypatch.setattr(troute, "_project_or_404",
                        lambda slug: ({"path": ".", "name": "P", "slug": slug}, None))
    monkeypatch.setattr(troute, "_ticket_or_404", lambda slug, tid: (ticket, None))
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(troute.tickets, "coder_report", lambda t: "")
    monkeypatch.setattr(troute.tickets, "build_validator_prompt", lambda t, d, r: "validate me")
    monkeypatch.setattr(troute.tickets, "add_run", lambda *a, **k: None)

    def _create_agent(prompt, model, cwd, **kw):
        captured["parent"] = kw.get("parent")
        captured["run_kind"] = kw.get("run_kind")
        return SimpleNamespace(agent_id="validator-1")

    monkeypatch.setattr(troute.runner, "create_agent", _create_agent)

    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    c._captured = captured
    return c


def test_manual_validate_nests_under_coder(monkeypatch):
    # ticket AVEC un run 'work' → le validateur manuel doit être rattaché au codeur (agent_id).
    ticket = {
        "id": "tk1", "title": "T", "prompt": "fix it",
        "parent": "mgr-42",
        "runs": [{"kind": "work", "agent_id": "coder-99"}],
    }
    client = _make_client(monkeypatch, ticket)
    r = client.post("/api/tickets/proj/tk1/validate", json={})
    assert r.status_code == 200
    assert r.get_json() == {"key": "agent/validator-1"}
    assert client._captured["parent"] == "coder-99"  # imbriqué sous le codeur, pas orphelin
    assert client._captured["run_kind"] == "validate"  # branche merge/rework inchangée


def test_manual_validate_without_work_run_defaults_to_dispatcher(monkeypatch):
    # ticket SANS run 'work' → parent 'dispatcher:validate', pas de crash.
    ticket = {"id": "tk2", "title": "T2", "prompt": "fix it", "parent": "mgr-7", "runs": []}
    client = _make_client(monkeypatch, ticket)
    r = client.post("/api/tickets/proj/tk2/validate", json={})
    assert r.status_code == 200
    assert client._captured["parent"] == "dispatcher:validate"
    assert client._captured["run_kind"] == "validate"
