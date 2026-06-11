"""Test that turn_detail exposes the full content of each item (not just preview)."""

import types
from unittest.mock import MagicMock
from pathlib import Path

import pytest


@pytest.fixture()
def fake_extract(monkeypatch):
    """Patch extract_per_call_data to return controlled items with text + preview."""
    from bouzecode.web_v2.services.sessions import analysis

    fake_items = [
        {
            "kind": "system_prompt",
            "label": "System",
            "est_tokens": 500,
            "cache_status": "cached",
            "preview": "Tu es un agent...",
            "text": "Tu es un agent de code. Voici tes instructions complètes qui sont très longues et ne doivent pas être tronquées.",
        },
        {
            "kind": "user_message",
            "label": "User msg",
            "est_tokens": 100,
            "cache_status": "fresh",
            "preview": "Corrige le bug...",
            "text": "Corrige le bug dans config.py ligne 42 où la valeur par défaut est None au lieu de 'default'.",
        },
    ]

    def fake_extract_fn(session_path: str):
        return {
            "session_id": "test-session",
            "model": "test-model",
            "saved_at": "2026-01-01",
            "first_message": "hello",
            "system_prompt_tokens": 500,
            "calls": [
                {
                    "turn": 1,
                    "timestamp": "2026-01-01T00:00:00",
                    "user_prompt": "Corrige le bug",
                    "api_input_tokens": 600,
                    "api_output_tokens": 200,
                    "api_cache_read": 500,
                    "api_cache_create": 0,
                    "est_message_tokens": 600,
                    "wire_message_count": 3,
                    "items": fake_items,
                    "tokens_by_status": {"cached": 500, "fresh": 100},
                    "count_by_status": {"cached": 1, "fresh": 1},
                    "breakpoint_payload_idx": 1,
                    "prev_breakpoint_payload_idx": -1,
                    "divergence_payload_idx": 0,
                },
            ],
        }

    monkeypatch.setattr(analysis, "extract_per_call_data", fake_extract_fn)

    # Also patch _response_html to avoid needing real session files
    monkeypatch.setattr(analysis, "_response_html", lambda *a, **kw: "<p>mock</p>")
    return fake_items


def test_turn_detail_exposes_full_content(fake_extract):
    """turn_detail must include 'content' field with full text, not truncated."""
    from bouzecode.web_v2.services.sessions import analysis

    result = analysis.turn_detail("fake/path.json", turn=1)
    assert result is not None
    items = result["items"]
    assert len(items) == 2

    # First item: content must be the full text, not the preview
    assert items[0]["content"] == (
        "Tu es un agent de code. Voici tes instructions complètes "
        "qui sont très longues et ne doivent pas être tronquées."
    )
    assert items[0]["preview"] == "Tu es un agent..."

    # Second item
    assert items[1]["content"] == (
        "Corrige le bug dans config.py ligne 42 où la valeur par défaut "
        "est None au lieu de 'default'."
    )
    assert items[1]["preview"] == "Corrige le bug..."


def test_turn_detail_content_fallback_to_preview(monkeypatch):
    """If item has no 'text' field, content should fall back to preview."""
    from bouzecode.web_v2.services.sessions import analysis

    item_no_text = {
        "kind": "tool_result",
        "label": "Bash output",
        "est_tokens": 50,
        "cache_status": "fresh",
        "preview": "$ echo hello",
    }

    def fake_extract_fn(session_path: str):
        return {
            "session_id": "s2",
            "model": "m",
            "saved_at": "2026-01-01",
            "first_message": "",
            "system_prompt_tokens": 0,
            "calls": [
                {
                    "turn": 1,
                    "timestamp": "2026-01-01T00:00:00",
                    "user_prompt": "",
                    "api_input_tokens": 50,
                    "api_output_tokens": 10,
                    "api_cache_read": 0,
                    "api_cache_create": 0,
                    "est_message_tokens": 50,
                    "wire_message_count": 1,
                    "items": [item_no_text],
                    "tokens_by_status": {"fresh": 50},
                    "count_by_status": {"fresh": 1},
                    "breakpoint_payload_idx": -1,
                    "prev_breakpoint_payload_idx": -1,
                    "divergence_payload_idx": 0,
                },
            ],
        }

    monkeypatch.setattr(analysis, "extract_per_call_data", fake_extract_fn)
    monkeypatch.setattr(analysis, "_response_html", lambda *a, **kw: "<p>mock</p>")

    result = analysis.turn_detail("fake/path.json", turn=1)
    assert result is not None
    # Fallback: content == preview when text is absent
    assert result["items"][0]["content"] == "$ echo hello"
