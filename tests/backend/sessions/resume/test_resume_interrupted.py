# [desc] A Ctrl+C'd web agent leaves its IPC state on 'running' so the restart sees a crash [/desc]
"""Crash recovery of web agents — unit level on purpose.

The behaviour under test happens between two *processes*: an agent subprocess
dies (Ctrl+C on the server) and the server, on restart, decides from the
leftover files on disk whether to respawn it. No bouzecode() conversation can
produce a half-dead subprocess plus its IPC state, so this stays a unit test
over the on-disk contract (agent JSON + IPC state.json + session JSON).

Regression pinned here: on Ctrl+C the agent used to write STATUS_FINISHED
before dying, so the restart saw "finished" and never resumed it. The IPC loop
now returns immediately on KeyboardInterrupt, leaving "running" — the marker the
restart logic reads as a crash.
"""
from bouzecode.web_v2.runtime.ipc import run_agent_event_loop, from_dir


class TestIpcEventLoopKeyboardInterrupt:
    def test_keyboard_interrupt_leaves_running_state(self, tmp_path, monkeypatch):
        """A Ctrl+C'd agent leaves its IPC state on 'running', so the next server
        start sees a crash to recover instead of a clean 'finished'."""
        ipc_dir = tmp_path / "ipc"
        ipc_dir.mkdir()
        paths = from_dir(str(ipc_dir))

        def raise_interrupt(prompt):
            raise KeyboardInterrupt()

        run_agent_event_loop("test", raise_interrupt, paths)

        from bouzecode.web_v2.runtime.ipc import read_state
        assert read_state(paths).get("status") == "running"
