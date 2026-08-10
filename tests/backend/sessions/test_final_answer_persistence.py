"""Test that final_answer is persisted in session JSON and exposed via web API."""

from bouzecode.backend.agent.state import AgentState, ContextState
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.web_v2.services.sessions.store import session_meta_full


def test_final_answer_serialized_in_session_data():
    """When state.final_answer is set, _build_session_data includes it."""
    state = AgentState()
    state.final_answer = "The task is complete."
    state.close_reason = "final_answer"

    data = _build_session_data(state)

    assert data["final_answer"] == "The task is complete."
    assert data["close_reason"] == "final_answer"


def test_final_answer_exposed_in_session_meta_full():
    """session_meta_full exposes final_answer from session data."""
    data = {
        "first_message": "do something",
        "model": "test-model",
        "turn_count": 3,
        "saved_at": "2026-06-10 22:00:00",
        "total_input_tokens": 100,
        "total_output_tokens": 50,
        "file_snapshots": {},
        "close_reason": "final_answer",
        "final_answer": "Here is the result.",
    }

    meta = session_meta_full(data)

    assert meta["final_answer"] == "Here is the result."
    assert meta["close_reason"] == "final_answer"


def test_session_meta_full_empty_for_old_sessions():
    """Old sessions without final_answer field → empty string."""
    data = {"first_message": "hi", "model": "x", "turn_count": 1}

    meta = session_meta_full(data)

    assert meta["final_answer"] == ""
    assert meta["close_reason"] == ""


def test_final_answer_empty_when_not_set():
    """State without final_answer → serialized as empty string."""
    state = AgentState()
    state.close_reason = "no_tools_text"

    data = _build_session_data(state)

    assert data["final_answer"] == ""
    assert data["close_reason"] == "no_tools_text"
