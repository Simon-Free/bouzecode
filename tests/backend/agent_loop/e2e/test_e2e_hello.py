# [desc] End-to-end tests verifying the bouzecode harness with real LLM calls: single-turn and multi-turn. [/desc]
"""E2E tests for the bouzecode harness.

These tests make REAL API calls — they require valid credentials in .env.
Run with: pytest tests/test_e2e_hello.py -m e2e -v
"""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.e2e_harness import bouzecode
from tests.cache_conversation_helpers import require_api_key


def test_single_turn():
    """Send a simple prompt, verify LLM responds correctly."""
    require_api_key()
    result = bouzecode(messages=["Say exactly this word and nothing else: PONG"])
    assert "PONG" in result.last_reply
    assert result.state.turn_count >= 1
    assert len(result.turns) == 1


def test_multi_turn():
    """Send two messages, verify conversation continuity."""
    require_api_key()
    result = bouzecode(messages=[
        "Remember this secret code: BANANA42. Just confirm you remembered it.",
        "What was the secret code I told you?",
    ])
    assert "BANANA42" in result.last_reply
    assert len(result.turns) == 2
    assert result.state.user_loop_count == 2
