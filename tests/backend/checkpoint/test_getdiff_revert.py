# [desc] Integration tests for GetDiff tool (file diffs) and /revert command (checkpoint rollback).
# <tool_use name="FinalAnswer" id="fa1"><param name="answer">Integration tests for GetDiff tool (file diffs) and /revert command (checkpoint rollback).</param></tool_use> [/desc]
"""Integration tests: GetDiff tool + /revert command."""
import os
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest


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


# ── GetDiff Tests ──


class TestGetDiff:
    def setup_method(self):
        from bouzecode.backend.tools.state import _file_edit_snapshots
        _file_edit_snapshots.clear()

    def teardown_method(self):
        from bouzecode.backend.tools.state import _file_edit_snapshots
        _file_edit_snapshots.clear()

    def test_no_changes(self):
        from bouzecode.backend.tools.ops.diff_ops import _get_diff
        result = _get_diff()
        assert result == "No changes recorded."

    def test_single_file_diff(self):
        from bouzecode.backend.tools.ops.diff_ops import _get_diff
        from bouzecode.backend.tools.state import _file_edit_snapshots

        _file_edit_snapshots["/tmp/test.py"] = {
            "before": "def hello():\n    pass\n",
            "after": "def hello():\n    print('hi')\n",
            "is_new": False,
        }

        result = _get_diff()
        assert "--- a//tmp/test.py" in result
        assert "+++ b//tmp/test.py" in result
        assert "-    pass" in result
        assert "+    print('hi')" in result

    def test_filter_by_path(self):
        from bouzecode.backend.tools.ops.diff_ops import _get_diff
        from bouzecode.backend.tools.state import _file_edit_snapshots

        _file_edit_snapshots["/tmp/a.py"] = {
            "before": "a\n", "after": "aa\n", "is_new": False,
        }
        _file_edit_snapshots["/tmp/b.py"] = {
            "before": "b\n", "after": "bb\n", "is_new": False,
        }

        result = _get_diff(file_path="/tmp/a.py")
        assert "/tmp/a.py" in result
        assert "/tmp/b.py" not in result

    def test_filter_nonexistent_path(self):
        from bouzecode.backend.tools.ops.diff_ops import _get_diff
        from bouzecode.backend.tools.state import _file_edit_snapshots

        _file_edit_snapshots["/tmp/a.py"] = {
            "before": "a\n", "after": "aa\n", "is_new": False,
        }

        result = _get_diff(file_path="/tmp/nonexistent.py")
        assert "No changes for /tmp/nonexistent.py" in result

    def test_new_file(self):
        from bouzecode.backend.tools.ops.diff_ops import _get_diff
        from bouzecode.backend.tools.state import _file_edit_snapshots

        _file_edit_snapshots["/tmp/new.py"] = {
            "before": None,
            "after": "print('new')\n",
            "is_new": True,
        }

        result = _get_diff()
        assert "/tmp/new.py" in result
        # Should show additions
        assert "+print('new')" in result


# ── Revert Command Tests ──


class TestRevertCmd:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="revert_test_"))
        self._orig_cwd = os.getcwd()
        os.chdir(str(self.tmpdir))

    def teardown_method(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_revert_no_session(self):
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert

        state = FakeState()
        config = {}
        result = cmd_revert("", state, config)
        assert result is True  # handled, just printed error

    def test_revert_no_snapshots(self, tmp_path, monkeypatch):
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert
        import bouzecode.backend.checkpoint.store as store

        # Use temp checkpoint root
        monkeypatch.setattr(store, "_checkpoints_root", lambda: tmp_path / ".ckpt")

        state = FakeState()
        config = {"_session_id": "empty_session"}
        result = cmd_revert("", state, config)
        assert result is True

    def test_revert_full_cycle(self, tmp_path, monkeypatch):
        """Full integration: write → snapshot → modify → revert → verify."""
        import bouzecode.backend.checkpoint.store as store
        from bouzecode.backend.checkpoint.hooks import set_session, get_tracked_edits, reset_tracked, _backup_before_write
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert

        # Isolate checkpoint storage
        monkeypatch.setattr(store, "_checkpoints_root", lambda: tmp_path / ".ckpt")

        session_id = "revert_integ"
        set_session(session_id)
        reset_tracked()

        # Step 1: Create a file, simulate turn 1
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

        tracked = get_tracked_edits()
        store.make_snapshot(session_id, state, config, "write code", tracked_edits=tracked)
        reset_tracked()

        # Step 2: Modify file, simulate turn 2
        _backup_before_write(str(test_file))
        test_file.write_text("def main(): print('changed')", encoding="utf-8")

        state.messages.extend([
            {"role": "user", "content": "change it"},
            {"role": "assistant", "content": "changed"},
        ])
        state.turn_count = 2
        state.total_input_tokens = 400
        state.total_output_tokens = 200

        tracked2 = get_tracked_edits()
        store.make_snapshot(session_id, state, config, "change it", tracked_edits=tracked2)
        reset_tracked()

        # Verify current state before revert
        assert test_file.read_text(encoding="utf-8") == "def main(): print('changed')"
        assert len(state.messages) == 4
        assert state.turn_count == 2

        # Step 3: Revert!
        result = cmd_revert("", state, config)
        assert result is True

        # Verify: file restored to state at snap 1 backup
        assert test_file.read_text(encoding="utf-8") == "def main(): pass"

        # Conversation should be restored to snap 1's message_index
        assert len(state.messages) == 2
        assert state.turn_count == 1
        assert state.total_input_tokens == 200

    def test_revert_restores_token_counters(self, tmp_path, monkeypatch):
        """Verify token counters are properly restored on revert."""
        import bouzecode.backend.checkpoint.store as store
        from bouzecode.backend.checkpoint.hooks import set_session, get_tracked_edits, reset_tracked, _backup_before_write
        from bouzecode.backend.commands.session.revert_cmd import cmd_revert

        monkeypatch.setattr(store, "_checkpoints_root", lambda: tmp_path / ".ckpt")

        session_id = "revert_tokens"
        set_session(session_id)
        reset_tracked()

        test_file = self.tmpdir / "data.txt"
        test_file.write_text("original", encoding="utf-8")
        _backup_before_write(str(test_file))

        state = FakeState(
            messages=[{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}],
            turn_count=1,
            total_input_tokens=100,
            total_output_tokens=50,
            total_cache_read_tokens=10,
            total_cache_creation_tokens=5,
            distinct_base=1,
        )
        config = {"_session_id": session_id}

        tracked = get_tracked_edits()
        store.make_snapshot(session_id, state, config, "q1", tracked_edits=tracked)
        reset_tracked()

        # Turn 2
        _backup_before_write(str(test_file))
        test_file.write_text("modified", encoding="utf-8")
        state.messages.extend([{"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}])
        state.turn_count = 2
        state.total_input_tokens = 300
        state.total_output_tokens = 150
        state.total_cache_read_tokens = 30
        state.total_cache_creation_tokens = 15
        state.distinct_base = 2

        tracked2 = get_tracked_edits()
        store.make_snapshot(session_id, state, config, "q2", tracked_edits=tracked2)
        reset_tracked()

        # Revert
        cmd_revert("", state, config)

        # Verify token counters restored to snap 1
        assert state.total_input_tokens == 100
        assert state.total_output_tokens == 50
        assert state.total_cache_read_tokens == 10
        assert state.total_cache_creation_tokens == 5
        assert state.distinct_base == 1
