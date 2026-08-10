# [desc] Test prouvant qu'une clôture gracieuse (final_answer/text_no_tools) stampe close_reason dans le session JSON. [/desc]
"""Prouve la cause racine du ticket : a la cloture gracieuse (FinalAnswer / text_no_tools),
le session JSON sur disque DOIT porter un close_reason non vide.

Avant le fix, les chemins gracieux de loop.py passaient close_reason uniquement en PARAMETRE
a _fire_completion (qui stampait l'IPC) sans jamais l'assigner sur state, donc
_build_session_data serialisait close_reason=''. Ce test joue le VRAI _fire_completion
avec un state minimal reel et un fichier session tmp, SANS unittest.mock.

Aucune env BOUZECODE_WEB_IPC_DIR n'est posee : completion_context resout alors self_id=''
et run_completion_chain retourne immediatement -> le hook on_completion ne fait AUCUN
http_post (zero reseau)."""
import json

from bouzecode.backend.agent.loop import _fire_completion


class _Notes:
    notes = ""


class _State:
    """State minimal reel : expose exactement les champs que _build_session_data lit."""

    def __init__(self):
        self.messages = [{"role": "user", "content": "do the thing"}]
        self.turn_count = 3
        self.total_input_tokens = 10
        self.total_output_tokens = 5
        self.context_state = _Notes()
        self.close_reason = ""  # sera pose par _fire_completion


def test_graceful_close_stamps_close_reason_in_session_json(tmp_path, monkeypatch):
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    session_file = tmp_path / "agent.session.json"
    state = _State()
    config = {"_session_file": str(session_file), "_session_id": "abcd1234", "model": "m"}

    _fire_completion(state, config, "final_answer")

    # (1) state porte le close_reason (base pour tout checkpoint ulterieur)
    assert state.close_reason == "final_answer"
    # (2) le session JSON sur disque le porte AUSSI (coeur du bug)
    assert session_file.exists()
    data = json.loads(session_file.read_text(encoding="utf-8"))
    assert data["close_reason"] == "final_answer"


def test_graceful_text_no_tools_also_stamped(tmp_path, monkeypatch):
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    session_file = tmp_path / "agent.session.json"
    state = _State()
    config = {"_session_file": str(session_file), "_session_id": "abcd1234", "model": "m"}

    _fire_completion(state, config, "text_no_tools")

    data = json.loads(session_file.read_text(encoding="utf-8"))
    assert data["close_reason"] == "text_no_tools"
