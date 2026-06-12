"""Tests for FinalAnswer display in web_v2 (accepted + refused cases)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bouzecode.web_v2.services import message_view
from bouzecode.web_v2.routes.sessions import _plain_block


# ---------------------------------------------------------------------------
# Fixtures — fake messages
# ---------------------------------------------------------------------------

ACCEPTED_CONTENT = (
    "Session closing — final answer delivered:\n"
    "Tous les fichiers ont été modifiés et les tests passent."
)

REFUSED_CONTENT = (
    "CLÔTURE REFUSÉE par le validateur — il manque : tests non lancés\n"
    "Termine ce qui manque (coche ta todolist) puis rappelle FinalAnswer."
)

NORMAL_TOOL_CONTENT = "File written successfully (42 bytes)."


def _tool_result_msg(name: str, content: str) -> dict:
    return {"role": "tool", "name": name, "content": content}


# ---------------------------------------------------------------------------
# Tests — _final_answer_kind
# ---------------------------------------------------------------------------

class TestFinalAnswerKind:
    def test_accepted(self):
        assert message_view._final_answer_kind("FinalAnswer", ACCEPTED_CONTENT) == "final_answer"

    def test_refused(self):
        assert message_view._final_answer_kind("FinalAnswer", REFUSED_CONTENT) == "final_answer_refused"

    def test_other_tool(self):
        assert message_view._final_answer_kind("Write", ACCEPTED_CONTENT) is None

    def test_final_answer_other_content(self):
        assert message_view._final_answer_kind("FinalAnswer", "Error: 'answer' is empty") is None


# ---------------------------------------------------------------------------
# Tests — render_message (HTML output)
# ---------------------------------------------------------------------------

class TestRenderMessage:
    def test_accepted_renders_final_answer_block(self):
        msg = _tool_result_msg("FinalAnswer", ACCEPTED_CONTENT)
        html_out = message_view.render_message(msg)
        assert 'class="block final-answer"' in html_out
        assert "Réponse finale" in html_out
        assert "tests passent" in html_out

    def test_refused_renders_refused_block(self):
        msg = _tool_result_msg("FinalAnswer", REFUSED_CONTENT)
        html_out = message_view.render_message(msg)
        assert 'class="block final-answer-refused"' in html_out
        assert "Clôture refusée" in html_out
        assert "tests non lancés" in html_out

    def test_normal_tool_unchanged(self):
        msg = _tool_result_msg("Write", NORMAL_TOOL_CONTENT)
        html_out = message_view.render_message(msg)
        assert 'class="tr"' in html_out
        assert "résultat Write" in html_out


# ---------------------------------------------------------------------------
# Tests — _plain_block (API plain=1)
# ---------------------------------------------------------------------------

class TestPlainBlock:
    def test_accepted_has_kind(self):
        msg = _tool_result_msg("FinalAnswer", ACCEPTED_CONTENT)
        block = _plain_block(0, msg)
        assert block["kind"] == "final_answer"

    def test_refused_has_kind(self):
        msg = _tool_result_msg("FinalAnswer", REFUSED_CONTENT)
        block = _plain_block(0, msg)
        assert block["kind"] == "final_answer_refused"

    def test_normal_tool_no_kind(self):
        msg = _tool_result_msg("Write", NORMAL_TOOL_CONTENT)
        block = _plain_block(0, msg)
        assert "kind" not in block

    def test_final_answer_unknown_content_no_kind(self):
        msg = _tool_result_msg("FinalAnswer", "Error: 'answer' is empty")
        block = _plain_block(0, msg)
        assert "kind" not in block


# ---------------------------------------------------------------------------
# Tests — Full API endpoint via Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Create a Flask test client with a fake session containing both cases."""
    from bouzecode.web_v2.app import create_app

    session_data = {
        "messages": [
            {"role": "user", "content": "Do something"},
            {"role": "assistant", "content": "Done.", "tool_calls": [
                {"name": "FinalAnswer", "input": {"answer": "All done"}}
            ]},
            _tool_result_msg("FinalAnswer", REFUSED_CONTENT),
            {"role": "assistant", "content": "Fixing...", "tool_calls": [
                {"name": "FinalAnswer", "input": {"answer": "Really done now"}}
            ]},
            _tool_result_msg("FinalAnswer", ACCEPTED_CONTENT),
        ]
    }
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(session_data), encoding="utf-8")

    # Patch store to return our fake session
    from bouzecode.web_v2.services.sessions import store
    fake_ref = MagicMock()
    fake_ref.path = session_file
    fake_ref.agent = None
    monkeypatch.setattr(store, "resolve", lambda key: fake_ref)
    monkeypatch.setattr(store, "load_session_json", lambda path: json.loads(path.read_text("utf-8")))
    monkeypatch.setattr(store, "session_meta_full", lambda data: {})

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestAPIBlocks:
    def test_plain_blocks_contain_kind(self, app_client):
        resp = app_client.get("/api/sessions/test-session/blocks?plain=1")
        assert resp.status_code == 200
        data = resp.get_json()
        blocks = data["blocks"]
        # Message index 2 = refused, index 4 = accepted
        refused_block = blocks[2]
        accepted_block = blocks[4]
        assert refused_block["kind"] == "final_answer_refused"
        assert accepted_block["kind"] == "final_answer"
        # Normal messages should not have kind
        assert "kind" not in blocks[0]
        assert "kind" not in blocks[1]

    def test_html_blocks_final_answer(self, app_client):
        resp = app_client.get("/api/sessions/test-session/blocks")
        assert resp.status_code == 200
        data = resp.get_json()
        blocks = data["blocks"]
        # Check HTML contains the expected classes
        refused_html = blocks[2]["html"]
        accepted_html = blocks[4]["html"]
        assert "final-answer-refused" in refused_html
        assert "final-answer" in accepted_html
        assert "Réponse finale" in accepted_html
