"""T7 — le recap structuré du codeur est formaté en markdown pour être poussé
dans le message de merge/PR. On construit un ticket avec un run kind=work qui
pointe une VRAIE session JSON sur disque, et on injecte un faux runner.load_agent
(fake pur, pas de mock) qui renvoie un agent dont session_path = ce fichier."""
import json
from pathlib import Path

from bouzecode.web_v2.services.work import integration


class _FakeAgent:
    def __init__(self, session_path: str):
        self.session_path = session_path


def _ticket_with_session(tmp_path: Path, monkeypatch, data: dict) -> dict:
    session = tmp_path / "coder.session.json"
    session.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ticket = {"runs": [{"kind": "work", "agent_id": "coder-1"}]}
    monkeypatch.setattr(integration.runner, "load_agent",
                        lambda agent_id: _FakeAgent(str(session)))
    return ticket


_RECAP = {
    "symptoms": "Le polling ne s'arrêtait jamais après la fin de la conversation.",
    "explanation": "Le timer se réarmait sans vérifier l'état running. Correctif : arrêt conditionnel.",
    "tests": "24 vitest verts dont un nouveau anti-réarmement.",
    "changes": [
        {"file": "src/bouzecode/web_v2/static/js/conversations.js",
         "summary": "Conditionne la re-programmation du poller à l'état running."},
        {"file": "src/bouzecode/web_v2/tests/js/conversations.test.js",
         "summary": "Ajoute un test anti-réarmement après 'done'."},
    ],
}


def test_coder_recap_body_formats_markdown(tmp_path, monkeypatch):
    ticket = _ticket_with_session(tmp_path, monkeypatch, {"recap": _RECAP})

    body = integration._coder_recap_body(ticket)

    assert "## Symptoms" in body
    assert "## Explanation" in body
    assert "## Tests" in body
    assert "## Changes" in body
    assert _RECAP["symptoms"] in body
    assert _RECAP["explanation"] in body
    assert _RECAP["tests"] in body
    # changes rendus en liste ORDONNÉE file — summary, dans l'ordre de recap.changes
    idx_js = body.index("conversations.js")
    idx_test = body.index("conversations.test.js")
    assert idx_js < idx_test
    assert "Conditionne la re-programmation du poller" in body


def test_coder_recap_body_empty_when_no_recap(tmp_path, monkeypatch):
    ticket = _ticket_with_session(tmp_path, monkeypatch, {"diff": "x"})  # pas de recap
    assert integration._coder_recap_body(ticket) == ""


def test_coder_recap_body_empty_when_no_work_run(tmp_path, monkeypatch):
    ticket = {"runs": [{"kind": "validate", "agent_id": "v-1"}]}
    monkeypatch.setattr(integration.runner, "load_agent", lambda a: None)
    assert integration._coder_recap_body(ticket) == ""
