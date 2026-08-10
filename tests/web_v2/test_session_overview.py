# [desc] Tests for GET /api/sessions/<key>/overview endpoint: truncation, error preservation, JSON mode, pagination. [/desc]
"""Verify session overview endpoint: one line per turn, truncation, errors intact, JSON mode, pagination."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_session_data() -> dict:
    """Build a realistic session with tool_calls, long output, error, and final_answer."""
    long_output = "\n".join(f"line {i}: some data here" for i in range(200))
    error_output = "Error: FileNotFoundError — /tmp/missing.py does not exist"

    messages = [
        # Turn 1: user message
        {"role": "user", "content": "Please fix the bug in parser.py"},
        # Turn 1: assistant response with tool_calls
        {
            "role": "assistant",
            "content": "I'll read the file first.",
            "tool_calls": [
                {"name": "Read", "input": json.dumps({"file_path": "/tmp/parser.py"})},
                {"name": "Grep", "input": json.dumps({"pattern": "def parse", "path": "/tmp"})},
            ],
        },
        # Turn 1: tool results
        {"role": "tool", "content": long_output, "name": "Read"},
        {"role": "tool", "content": error_output, "name": "Grep", "is_error": True},
        # Turn 2: continue (no user message before assistant)
        {
            "role": "assistant",
            "content": "The grep failed, let me try another approach.\nI'll edit directly.",
            "tool_calls": [
                {"name": "Edit", "input": json.dumps({"file_path": "/tmp/parser.py", "old_string": "x", "new_string": "y"})},
            ],
        },
        {"role": "tool", "content": "OK — edited 1 occurrence", "name": "Edit"},
        # Turn 3: user follow-up
        {"role": "user", "content": "Now run the tests"},
        {
            "role": "assistant",
            "content": "Running tests now.",
            "tool_calls": [
                {"name": "RunPythonTest", "input": json.dumps({"targets": ["tests/"]})},
            ],
        },
        {"role": "tool", "content": "All 5 tests passed.", "name": "RunPythonTest"},
        # Turn 4: final answer
        {
            "role": "assistant",
            "content": "Done! The bug was a typo in parser.py line 42.\nI fixed it and all tests pass.\nHere is the summary of changes.",
        },
    ]

    return {
        "model": "claude-sonnet-4-20250514",
        "turn_count": 4,
        "total_input_tokens": 15000,
        "total_output_tokens": 3000,
        "close_reason": "final_answer",
        "final_answer": "Done! The bug was a typo in parser.py line 42.\nI fixed it and all tests pass.\nHere is the summary of changes.",
        "saved_at": "2026-06-12T10:00:00",
        "first_message": "Please fix the bug in parser.py",
        "messages": messages,
    }


@pytest.fixture()
def _fake_overview_session(tmp_path, monkeypatch):
    """Create a fake session and patch store to resolve it."""
    from bouzecode.web_v2.services.sessions import store
    from bouzecode.web_v2.services.sessions.store import runner as _runner

    daily_dir = tmp_path / "daily"
    day_dir = daily_dir / "2026-06-12"
    day_dir.mkdir(parents=True)

    session_path = day_dir / "session_overview_test.json"
    session_path.write_text(json.dumps(_make_session_data()), encoding="utf-8")

    monkeypatch.setattr(store, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(_runner, "list_agents", lambda: [])


@pytest.fixture()
def client(_fake_overview_session):
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


SESSION_KEY = "daily/2026-06-12/session_overview_test.json"


class TestOverviewPlainText:
    """Tests for text/plain response (default)."""

    def test_returns_200(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        assert resp.status_code == 200

    def test_content_type_is_text(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        assert "text/plain" in resp.content_type

    def test_header_contains_model(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        assert "claude-sonnet-4-20250514" in text

    def test_header_contains_tokens(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        assert "15000" in text  # input tokens
        assert "3000" in text   # output tokens

    def test_one_entry_per_turn(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        # Should have turn markers T1, T2, T3, T4
        assert "T1" in text
        assert "T2" in text
        assert "T3" in text
        assert "T4" in text

    def test_tool_calls_listed(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        assert "Read(" in text
        assert "Grep(" in text
        assert "Edit(" in text

    def test_error_marked(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        # Error tool results should show failure marker
        assert "✗" in text

    def test_success_marked(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        assert "✓" in text

    def test_zoom_pointers_present(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        assert f"/api/sessions/{SESSION_KEY}/turns/" in text

    def test_final_answer_truncated_2_lines(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        # final_answer is 3 lines; should be truncated to 2
        assert "Here is the summary" not in text  # 3rd line cut
        assert "bug was a typo" in text  # 1st line present

    def test_close_reason_shown(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview")
        text = resp.get_data(as_text=True)
        assert "final_answer" in text


class TestOverviewJSON:
    """Tests for ?json=1 response."""

    def test_json_mode_returns_json(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview?json=1")
        assert resp.status_code == 200
        assert "application/json" in resp.content_type

    def test_json_indented(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview?json=1")
        text = resp.get_data(as_text=True)
        # Indented JSON has newlines and spaces
        assert "\n" in text
        assert "  " in text

    def test_json_has_header_and_turns(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview?json=1")
        data = json.loads(resp.get_data(as_text=True))
        assert "header" in data
        assert "turns" in data
        assert data["header"]["model"] == "claude-sonnet-4-20250514"
        assert len(data["turns"]) == 4


class TestOverviewPagination:
    """Tests for after/limit pagination."""

    def test_limit_restricts_turns(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview?json=1&limit=2")
        data = json.loads(resp.get_data(as_text=True))
        assert len(data["turns"]) == 2

    def test_after_skips_turns(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview?json=1&after=2")
        data = json.loads(resp.get_data(as_text=True))
        # Turns 3 and 4 (0-indexed after=2 means start from turn index 2)
        assert len(data["turns"]) == 2
        assert data["turns"][0]["index"] == 3

    def test_after_and_limit_combined(self, client):
        resp = client.get(f"/api/sessions/{SESSION_KEY}/overview?json=1&after=1&limit=1")
        data = json.loads(resp.get_data(as_text=True))
        assert len(data["turns"]) == 1
        assert data["turns"][0]["index"] == 2


class TestOverview404:
    """Test missing session."""

    def test_unknown_key_returns_404(self, client):
        resp = client.get("/api/sessions/daily/2099-01-01/nope.json/overview")
        assert resp.status_code == 404


class TestFormatterUnit:
    """Unit tests for formatter functions."""

    def test_pretty_json_from_dict(self):
        from bouzecode.web_v2.services.sessions.formatter import pretty_json
        result = pretty_json({"a": 1, "b": [2, 3]})
        assert '"a": 1' in result
        assert "\n" in result

    def test_pretty_json_from_string(self):
        from bouzecode.web_v2.services.sessions.formatter import pretty_json
        result = pretty_json('{"x": "hello"}')
        assert '"x": "hello"' in result
        assert "\n" in result

    def test_pretty_json_invalid_string_passthrough(self):
        from bouzecode.web_v2.services.sessions.formatter import pretty_json
        result = pretty_json("not json at all")
        assert result == "not json at all"

    def test_truncate_block_short_text_unchanged(self):
        from bouzecode.web_v2.services.sessions.formatter import truncate_block
        short = "line1\nline2\nline3"
        assert truncate_block(short) == short

    def test_truncate_block_long_text_has_marker(self):
        from bouzecode.web_v2.services.sessions.formatter import truncate_block
        long_text = "\n".join(f"line {i}" for i in range(100))
        result = truncate_block(long_text, head=10, tail=5, zoom_hint="/zoom/here")
        assert "lignes omises" in result or "lines omitted" in result or "omises" in result
        assert "/zoom/here" in result
        # Head and tail present
        assert "line 0" in result
        assert "line 99" in result
        # Middle cut
        assert "line 50" not in result

    def test_truncate_block_error_never_cut(self):
        from bouzecode.web_v2.services.sessions.formatter import truncate_block
        error_text = "\n".join(f"error line {i}" for i in range(100))
        result = truncate_block(error_text, head=10, tail=5, zoom_hint="/z", is_error=True)
        # Error content should be returned in full
        assert result == error_text

    def test_resolve_overflow_pointer_found(self):
        from bouzecode.web_v2.services.sessions.formatter import resolve_overflow_pointer
        text = (
            "some output\n\n"
            "[...output truncated — 500 lines total, full output saved to: "
            "C:/Users/me/.bouzecode/tool_outputs/bash_123_456.txt]\n"
            '[Use Read(file_path="C:/Users/me/.bouzecode/tool_outputs/bash_123_456.txt") '
            "to see the complete output]"
        )
        path = resolve_overflow_pointer(text)
        assert path == "C:/Users/me/.bouzecode/tool_outputs/bash_123_456.txt"

    def test_resolve_overflow_pointer_not_found(self):
        from bouzecode.web_v2.services.sessions.formatter import resolve_overflow_pointer
        assert resolve_overflow_pointer("normal text") is None
