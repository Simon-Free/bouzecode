# [desc] Round-trip save→restore d'une session : les champs de clôture/télémétrie survivent au reload. [/desc]
"""Régression FIX restore_state : `_build_session_data` sauvegarde close_reason/final_answer/
total_tool_calls/meta_only_nudges/thinking_log, mais `restore_state` les OMETTAIT au reload →
une session REPRISE paraissait « jamais finie / 0 outil » (télémétrie fausse). No mock.patch."""
from __future__ import annotations

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.session.session_pick import restore_state


def test_closure_fields_survive_save_restore():
    src = AgentState()
    src.total_tool_calls = 42
    src.meta_only_nudges = 3
    src.thinking_log = [{"turn": 1, "text": "réflexion"}]
    src.close_reason = "final_answer"
    src.final_answer = "Livraison terminée."
    src.turn_count = 7

    data = _build_session_data(src, session_id="abc123", model="opus")
    restored = AgentState()
    restore_state(restored, data)

    assert restored.total_tool_calls == 42
    assert restored.meta_only_nudges == 3
    assert restored.thinking_log == [{"turn": 1, "text": "réflexion"}]
    assert restored.close_reason == "final_answer"
    assert restored.final_answer == "Livraison terminée."
    assert restored.turn_count == 7


def test_runtime_fields_not_restored_from_snapshot():
    """system_prompt/bouzecode_commit/version = valeurs du RUN COURANT, jamais restaurées
    depuis un vieux snapshot (sinon un resume afficherait la version de la session d'origine)."""
    src = AgentState()
    src.bouzecode_commit = "oldsha"
    src.bouzecode_version = "1.0.0"
    data = _build_session_data(src, session_id="abc123", model="opus")
    restored = AgentState()  # défauts = run courant
    restore_state(restored, data)
    assert restored.bouzecode_commit == ""
    assert restored.bouzecode_version == ""
