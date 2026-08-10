"""Zoom sur une session : lire un tour entier, puis zoomer sur un appel d'outil.

L'interface propose deux niveaux de lecture. `/turns/<n>/view` donne le tour en
entier, mais raccourcit les longs résultats et renvoie vers l'appel concerné.
`/calls/<call_id>` sert alors cet appel sans rien couper — y compris quand la sortie
avait été déportée dans un fichier.
"""

import json

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LONG_RESULT = "\n".join(f"line {i}" for i in range(1, 101))  # 100 lines

OVERFLOW_POINTER = (
    "[...output truncated — 5000 lines total, full output saved to: {path}]\n"
    '[Use Read(file_path="{path}") to see the complete output]'
)

SESSION_WITH_TOOLS = {
    "messages": [
        {"role": "user", "content": "Please help"},
        {
            "role": "assistant",
            "content": "<thinking>\nthought 1\nthought 2\nthought 3\nthought 4\nthought 5\n</thinking>\n\nI'll fix the bug.",
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "name": "Edit",
                    "input": {
                        "file_path": "/some/path.py",
                        "old_string": "x = 1",
                        "new_string": "x = 2",
                    },
                },
                {
                    "id": "call_def456",
                    "name": "Read",
                    "input": {"file_path": "/some/other.py"},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_abc123",
            "content": "Edit applied successfully.",
        },
        {
            "role": "tool",
            "tool_call_id": "call_def456",
            "content": LONG_RESULT,
        },
        # Turn 2 — with an error result
        {"role": "user", "content": "Now run tests"},
        {
            "role": "assistant",
            "content": "Running tests.",
            "tool_calls": [
                {
                    "id": "call_err789",
                    "name": "RunPythonTest",
                    "input": {"targets": ["tests/"]},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_err789",
            "content": "FAILED: test_foo.py::test_bar - AssertionError",
            "is_error": True,
        },
    ],
}


def _client_serving(session_data: dict, session_file, monkeypatch):
    """Client Flask dont la clé 'test-sess' résout vers cette session écrite sur disque."""
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.services.sessions import store

    session_file.write_text(json.dumps(session_data), encoding="utf-8")
    ref = store.SessionRef(key="test-sess", kind="daily", path=session_file)

    monkeypatch.setattr(store, "resolve", lambda key: ref)
    monkeypatch.setattr(store, "load_session_json", lambda path: json.loads(path.read_text("utf-8")))
    monkeypatch.setattr(store, "session_meta_full", lambda data: {})

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Une session de 2 tours : des appels d'outil, un résultat long, un résultat en erreur."""
    return _client_serving(SESSION_WITH_TOOLS, tmp_path / "session.json", monkeypatch)


@pytest.fixture()
def overflow_client(tmp_path, monkeypatch):
    """Une session dont le résultat d'outil a été déporté dans un fichier (sortie trop grosse)."""
    # Create the overflow dump file
    dump_dir = tmp_path / "tool_outputs"
    dump_dir.mkdir()
    dump_file = dump_dir / "call_over999.txt"
    dump_content = json.dumps({"key": "value", "items": list(range(50))})
    dump_file.write_text(dump_content, encoding="utf-8")

    pointer_text = OVERFLOW_POINTER.format(path=str(dump_file))

    session_data = {
        "messages": [
            {"role": "user", "content": "Fetch data"},
            {
                "role": "assistant",
                "content": "Fetching.",
                "tool_calls": [
                    {
                        "id": "call_over999",
                        "name": "WebFetch",
                        "input": {"url": "https://example.com/api"},
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_over999",
                "content": pointer_text,
            },
        ],
    }

    return _client_serving(session_data, tmp_path / "session.json", monkeypatch)


# ---------------------------------------------------------------------------
# Tests — GET /api/sessions/<key>/turns/<n>/view
# ---------------------------------------------------------------------------


class TestTurnView:
    """Tests for the turn view endpoint."""

    def test_turn_view_plain_has_assistant_text(self, app_client):
        """Turn 1 should contain the assistant's visible text."""
        resp = app_client.get("/api/sessions/test-sess/turns/1/view")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/plain")
        text = resp.get_data(as_text=True)
        # Assistant text (without thinking) should appear
        assert "I'll fix the bug." in text

    def test_turn_view_thinking_summary_by_default(self, app_client):
        """By default, thinking is shown as a summary (size + first 3 lines)."""
        resp = app_client.get("/api/sessions/test-sess/turns/1/view")
        text = resp.get_data(as_text=True)
        # Should mention thinking size but NOT show full content
        assert "thinking" in text.lower()
        assert "thought 4" not in text  # thought 4 is beyond first 3 lines

    def test_turn_view_thinking_full_with_param(self, app_client):
        """?thinking=1 shows the full thinking content."""
        resp = app_client.get("/api/sessions/test-sess/turns/1/view?thinking=1")
        text = resp.get_data(as_text=True)
        assert "thought 4" in text
        assert "thought 5" in text

    def test_turn_view_tool_args_indented(self, app_client):
        """Tool call args should appear as indented JSON."""
        resp = app_client.get("/api/sessions/test-sess/turns/1/view")
        text = resp.get_data(as_text=True)
        # Edit args should be pretty-printed
        assert '"file_path": "/some/path.py"' in text
        # Indentation check (2 spaces)
        assert '  "old_string": "x = 1"' in text

    def test_turn_view_result_truncated_with_pointer(self, app_client):
        """Long tool results are truncated with a zoom pointer."""
        resp = app_client.get("/api/sessions/test-sess/turns/1/view")
        text = resp.get_data(as_text=True)
        # The 100-line result should be truncated
        assert "lignes omises" in text
        # Should have a zoom pointer to the call
        assert "/api/sessions/test-sess/calls/call_def456" in text

    def test_turn_view_error_never_truncated(self, app_client):
        """Error results are NEVER truncated."""
        resp = app_client.get("/api/sessions/test-sess/turns/2/view")
        text = resp.get_data(as_text=True)
        # The error content should appear fully
        assert "FAILED: test_foo.py::test_bar - AssertionError" in text
        # No truncation marker
        assert "lignes omises" not in text

    def test_turn_view_json_mode(self, app_client):
        """?json=1 returns structured JSON."""
        resp = app_client.get("/api/sessions/test-sess/turns/1/view?json=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "assistant_content" in data
        assert "tool_calls" in data
        assert isinstance(data["tool_calls"], list)

    def test_turn_view_404_invalid_index(self, app_client):
        """Invalid turn index returns 404."""
        resp = app_client.get("/api/sessions/test-sess/turns/99/view")
        assert resp.status_code == 404

    def test_turn_index_consistency_with_overview(self, app_client):
        """Turn indices in /view match those in /overview."""
        ov_resp = app_client.get("/api/sessions/test-sess/overview?json=1")
        assert ov_resp.status_code == 200
        ov_data = ov_resp.get_json()
        turns = ov_data["turns"]
        # Each overview turn index should be accessible via /view
        for turn in turns:
            idx = turn["index"]
            view_resp = app_client.get(f"/api/sessions/test-sess/turns/{idx}/view")
            assert view_resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests — GET /api/sessions/<key>/calls/<call_id>
# ---------------------------------------------------------------------------


class TestCallZoom:
    """Tests for the call zoom endpoint."""

    def test_call_zoom_returns_full_args_and_result(self, app_client):
        """Returns complete args + result for a given call_id."""
        resp = app_client.get("/api/sessions/test-sess/calls/call_abc123")
        assert resp.status_code == 200
        text = resp.get_data(as_text=True)
        # Full args
        assert '"file_path": "/some/path.py"' in text
        assert '"old_string": "x = 1"' in text
        # Full result
        assert "Edit applied successfully." in text

    def test_call_zoom_long_result_full(self, app_client):
        """Even long results are shown in full via /calls/."""
        resp = app_client.get("/api/sessions/test-sess/calls/call_def456")
        assert resp.status_code == 200
        text = resp.get_data(as_text=True)
        # All 100 lines should be present
        assert "line 1" in text
        assert "line 100" in text
        # No truncation
        assert "lignes omises" not in text

    def test_call_zoom_404_unknown_id(self, app_client):
        """Unknown call_id returns 404 with clear message."""
        resp = app_client.get("/api/sessions/test-sess/calls/call_nonexist")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
        assert "call_nonexist" in data["error"]

    def test_call_zoom_overflow_resolved(self, overflow_client):
        """Overflow pointer is resolved — full file content served."""
        resp = overflow_client.get("/api/sessions/test-sess/calls/call_over999")
        assert resp.status_code == 200
        text = resp.get_data(as_text=True)
        # The JSON content from the dump file should be pretty-printed
        assert '"key": "value"' in text
        assert '"items"' in text

    def test_call_zoom_json_mode(self, app_client):
        """?json=1 returns structured JSON for call zoom."""
        resp = app_client.get("/api/sessions/test-sess/calls/call_abc123?json=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "name" in data
        assert data["name"] == "Edit"
        assert "args" in data
        assert "result" in data
