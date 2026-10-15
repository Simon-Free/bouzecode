# [desc] Tests que la pause AskUserQuestion et l'état IPC transportent bien les options proposées. [/desc]
"""Une question posée à l'utilisateur garde ses options, de la pause jusqu'à l'état IPC sur disque."""
import json

from bouzecode.backend.tools.interaction import PausedForInput
from bouzecode.web_v2.runtime.ipc import IPCPaths, read_state, write_state


class TestPausedForInputOptions:
    """PausedForInput should handle various option formats."""

    def test_paused_with_list_options(self):
        pause = PausedForInput(
            question="Test?",
            options=[{"label": "A"}, {"label": "B"}],
        )
        assert len(pause.options) == 2
        assert pause.options[0]["label"] == "A"

    def test_paused_with_none_options(self):
        pause = PausedForInput(question="Test?", options=None)
        assert pause.options == []

    def test_paused_is_plan_validation(self):
        pause = PausedForInput(
            question="Valides-tu ce plan ?",
            options=[{"label": "Oui"}],
            is_plan_validation=True,
        )
        assert pause.is_plan_validation is True


class TestIPCStateOptions:
    """Test that IPC state properly carries options."""

    def test_write_state_with_options(self, tmp_path):
        paths = IPCPaths(root=tmp_path)
        options = [{"label": "Yes"}, {"label": "No"}]
        write_state(paths, "awaiting_plan_validation", question="Approve?", options=options)
        state = read_state(paths)
        assert state["status"] == "awaiting_plan_validation"
        assert state["question"] == "Approve?"
        assert state["options"] == options
        assert isinstance(state["options"], list)

    def test_read_state_options_are_list(self, tmp_path):
        """Options stored as JSON should come back as list, not string."""
        paths = IPCPaths(root=tmp_path)
        payload = {
            "status": "awaiting_input",
            "question": "Pick one",
            "options": [{"label": "A"}, {"label": "B"}],
        }
        paths.state.write_text(json.dumps(payload), encoding="utf-8")
        state = read_state(paths)
        assert isinstance(state["options"], list)
        assert state["options"][0]["label"] == "A"
