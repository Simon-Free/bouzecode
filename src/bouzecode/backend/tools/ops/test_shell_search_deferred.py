from bouzecode.backend.context_manager.state import ContextState
from bouzecode.backend.tools.ops.shell_search import bash_handler


def test_bash_deferred_enqueues_without_running(tmp_path):
    marker = tmp_path / "SHOULD_NOT_RUN.txt"
    command = f'echo run > "{marker}"'
    context_state = ContextState()
    config = {"_context_state": context_state}

    result = bash_handler(
        {"command": command, "timeout": 240, "deferred": True}, config
    )

    # (a) command NOT executed: side-effect file must not exist
    assert not marker.exists()
    # (b) queue holds {command, timeout}
    assert context_state.deferred_queue == [{"command": command, "timeout": 240}]
    # (c) return string mentions deferred
    assert "deferred" in result
    # (d) notes['deferred'] is populated
    assert context_state.notes["deferred"]
    assert command.splitlines()[0] in context_state.notes["deferred"]
