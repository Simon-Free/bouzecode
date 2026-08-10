# [desc] Unit tests for the bookkeeping half of /revert: conversation and token counters rewound to the checkpoint, and the two "nothing to revert" cases. [/desc]
"""/revert bookkeeping — the part a conversation cannot show.

What a user sees of /revert (their files going back to the previous version) is
covered by a real conversation in test_getdiff_e2e.py::
test_revert_restores_the_file_as_it_was_before_the_last_request. What stays here
is the accounting the command also rewinds — message history, turn counter and
the four token totals — plus the two refusal paths (no session, no checkpoint).
Those need a state whose counters were driven to known values, which a mocked
conversation does not produce.

The GetDiff tests that used to live here (TestGetDiff, hand-seeded
_file_edit_snapshots) are gone: test_getdiff_e2e.py drives the same diffs through
real Write/Edit calls in a conversation.
"""
import os
import sys
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class FakeState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    distinct_base: int = 0
    turn_count: int = 0
    user_loop_count: int = 0


class TestRevertCmd:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="revert_test_"))
        self._orig_cwd = os.getcwd()
        os.chdir(str(self.tmpdir))

    def teardown_method(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_revert_without_a_session_reports_it_and_changes_nothing(self):
        """/revert outside a session tells the user instead of crashing."""
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert

        assert cmd_revert("", FakeState(), {}) is True

    def test_revert_without_any_checkpoint_reports_it(self, tmp_path, monkeypatch):
        """/revert with nothing checkpointed yet tells the user there is nothing
        to go back to."""
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert
        import bouzecode.backend.checkpoint.store as store

        monkeypatch.setattr(store, "_checkpoints_root", lambda: tmp_path / ".ckpt")

        assert cmd_revert("", FakeState(), {"_session_id": "empty_session"}) is True

    def test_revert_rewinds_the_conversation_to_the_previous_checkpoint(
        self, tmp_path, monkeypatch
    ):
        """Reverting also rewinds the conversation: messages and turn counter go
        back to the checkpoint taken before the last request."""
        import bouzecode.backend.checkpoint.store as store
        from bouzecode.backend.checkpoint.hooks import (
            set_session, get_tracked_edits, reset_tracked, _backup_before_write,
        )
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert

        monkeypatch.setattr(store, "_checkpoints_root", lambda: tmp_path / ".ckpt")

        session_id = "revert_integ"
        set_session(session_id)
        reset_tracked()

        test_file = self.tmpdir / "app.py"
        test_file.write_text("def main(): pass", encoding="utf-8")
        _backup_before_write(str(test_file))

        state = FakeState(
            messages=[
                {"role": "user", "content": "write code"},
                {"role": "assistant", "content": "done"},
            ],
            turn_count=1,
            total_input_tokens=200,
            total_output_tokens=100,
        )
        config = {"_session_id": session_id}

        store.make_snapshot(session_id, state, config, "write code",
                            tracked_edits=get_tracked_edits())
        reset_tracked()

        # Second request: the file and the counters move on.
        _backup_before_write(str(test_file))
        test_file.write_text("def main(): print('changed')", encoding="utf-8")
        state.messages.extend([
            {"role": "user", "content": "change it"},
            {"role": "assistant", "content": "changed"},
        ])
        state.turn_count = 2
        state.total_input_tokens = 400
        state.total_output_tokens = 200
        store.make_snapshot(session_id, state, config, "change it",
                            tracked_edits=get_tracked_edits())
        reset_tracked()

        assert cmd_revert("", state, config) is True

        assert test_file.read_text(encoding="utf-8") == "def main(): pass"
        assert len(state.messages) == 2
        assert state.turn_count == 1
        assert state.total_input_tokens == 200

    def test_revert_restores_the_token_counters(self, tmp_path, monkeypatch):
        """The cost counters shown to the user are rewound too, so a reverted
        turn stops being billed in the session total."""
        import bouzecode.backend.checkpoint.store as store
        from bouzecode.backend.checkpoint.hooks import (
            set_session, get_tracked_edits, reset_tracked, _backup_before_write,
        )
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert

        monkeypatch.setattr(store, "_checkpoints_root", lambda: tmp_path / ".ckpt")

        session_id = "revert_tokens"
        set_session(session_id)
        reset_tracked()

        test_file = self.tmpdir / "data.txt"
        test_file.write_text("original", encoding="utf-8")
        _backup_before_write(str(test_file))

        state = FakeState(
            messages=[{"role": "user", "content": "q1"},
                      {"role": "assistant", "content": "a1"}],
            turn_count=1,
            total_input_tokens=100,
            total_output_tokens=50,
            total_cache_read_tokens=10,
            total_cache_creation_tokens=5,
            distinct_base=1,
        )
        config = {"_session_id": session_id}
        store.make_snapshot(session_id, state, config, "q1",
                            tracked_edits=get_tracked_edits())
        reset_tracked()

        _backup_before_write(str(test_file))
        test_file.write_text("modified", encoding="utf-8")
        state.messages.extend([{"role": "user", "content": "q2"},
                               {"role": "assistant", "content": "a2"}])
        state.turn_count = 2
        state.total_input_tokens = 300
        state.total_output_tokens = 150
        state.total_cache_read_tokens = 30
        state.total_cache_creation_tokens = 15
        state.distinct_base = 2
        store.make_snapshot(session_id, state, config, "q2",
                            tracked_edits=get_tracked_edits())
        reset_tracked()

        cmd_revert("", state, config)

        assert state.total_input_tokens == 100
        assert state.total_output_tokens == 50
        assert state.total_cache_read_tokens == 10
        assert state.total_cache_creation_tokens == 5
        assert state.distinct_base == 1
