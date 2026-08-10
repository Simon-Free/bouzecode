"""Tests for the temp=True scratch tooling on Write/Edit/Read.

Level: backend logic (pytest). NOT a browser test — temp=True is a harness
tool with no UI. We assert the structural guarantee: temp files live OUTSIDE
the git worktree (under the OS temp dir) and are never written into cwd, so
they can never be tracked/committed; and cleanup destroys them.
"""
from pathlib import Path

import pytest

import shutil
import uuid

from bouzecode.backend.tools.ops.file_ops import _write, _read, _edit
from bouzecode.backend.tools.ops.shell_search import _bash, _glob, _grep
from bouzecode.backend.tools.ops import scratch


@pytest.fixture(autouse=True)
def _clean_scratch():
    # Isolate each test in its own scratch session so parallel xdist workers
    # never share the "default" scratch dir / _registry.json (a neighbour's
    # cleanup would rmtree files another worker is still using).
    scratch.set_scratch_session(f"test-{uuid.uuid4().hex}")
    yield
    scratch.cleanup_scratch()


def test_write_temp_creates_file_outside_worktree(tmp_path):
    logical = str(tmp_path / "dump.txt")
    res = _write(logical, "hello temp", temp=True)
    assert "[scratch]" in res
    # The real file must NOT be at the logical path (which is inside the test
    # worktree/tmp), it must live in the scratch dir under the OS temp dir.
    assert not Path(logical).exists(), "temp write must NOT touch the logical path"
    real = scratch.lookup_temp(logical)
    assert real is not None
    assert Path(real).exists()
    assert scratch.is_scratch_path(real)


def test_read_reads_back_temp_content(tmp_path):
    logical = str(tmp_path / "dump.txt")
    _write(logical, "line one\nline two", temp=True)
    out = _read(logical)
    assert "line one" in out
    assert "line two" in out


def test_edit_modifies_temp_file(tmp_path):
    logical = str(tmp_path / "dump.txt")
    _write(logical, "before value", temp=True)
    res = _edit(logical, "before", "after", temp=True)
    assert "Error" not in res
    out = _read(logical)
    assert "after value" in out
    assert "before value" not in out


def test_edit_temp_without_prior_write_errors(tmp_path):
    logical = str(tmp_path / "never_written.txt")
    res = _edit(logical, "a", "b", temp=True)
    assert "Error" in res
    assert "no temp file registered" in res


def test_cleanup_destroys_scratch_and_registry(tmp_path):
    logical = str(tmp_path / "dump.txt")
    _write(logical, "content", temp=True)
    real = scratch.lookup_temp(logical)
    assert Path(real).exists()

    scratch.cleanup_scratch()

    assert scratch.lookup_temp(logical) is None
    assert not Path(real).exists()
    # Read after cleanup: registry empty -> falls back to logical path, absent.
    out = _read(logical)
    assert "file not found" in out


def test_temp_file_never_in_logical_location(tmp_path):
    """The whole point: a temp file is structurally uncommittable because it
    is never written into the (git) worktree location."""
    logical = str(tmp_path / "artifact.bin")
    _write(logical, "debug blob", temp=True)
    assert not Path(logical).exists()


# --- VOLET 1: Write(temp=True) result exposes the real path + shell warning ---

def test_write_temp_result_exposes_real_path_and_shell_warning(tmp_path):
    logical = str(tmp_path / "temp_out.txt")
    res = _write(logical, "payload", temp=True)
    real = scratch.lookup_temp(logical)
    assert real is not None
    # The result must surface the REAL path so the agent can use it in the shell.
    assert real in res
    # And warn that Bash/Glob/Grep do not see the logical path directly.
    low = res.lower()
    assert "bash" in low and ("chemin réel" in low or "chemin reel" in low or "real" in low)


# --- VOLET 2: Bash resolves logical scratch paths to real ones ---

def test_bash_resolves_logical_scratch_path_in_command(tmp_path):
    """Bash must substitute a registered logical path by its real path so a
    command referring to the logical name actually reads the scratch file."""
    logical = str(tmp_path / "temp_data.txt")
    _write(logical, "SCRATCH_MARKER_42", temp=True)
    # Windows: `type <path>` prints the file content. The logical path does NOT
    # exist on disk, so this only works if Bash rewrote it to the real path.
    out = _bash(f'type "{logical}"')
    assert "SCRATCH_MARKER_42" in out


def test_bash_executes_logical_temp_script(tmp_path):
    """A temp=True *script* must be executable via its logical name."""
    py = shutil.which("python") or shutil.which("python3")
    if not py:
        pytest.skip("no python interpreter on PATH")
    logical = str(tmp_path / "temp_script.py")
    _write(logical, "print('HELLO_FROM_SCRATCH')", temp=True)
    out = _bash(f'python "{logical}"')
    assert "HELLO_FROM_SCRATCH" in out
    # Zero write into the (git) worktree: the logical path stays absent.
    assert not Path(logical).exists()


def test_bash_substitution_respects_token_boundary(tmp_path):
    """A logical path must not be substituted when it is only a substring of a
    longer token (temp_a.txt must not be rewritten inside temp_ab.txt)."""
    short = str(tmp_path / "temp_a.txt")
    _write(short, "SHORT_CONTENT", temp=True)
    real_short = scratch.lookup_temp(short)
    longer = str(tmp_path / "temp_ab.txt")  # NOT registered
    out = _bash(f'echo "{longer}"')
    # The unregistered longer path must be echoed verbatim, not rewritten to the
    # short one's real path.
    assert longer in out
    assert real_short not in out


# --- VOLET 3: Glob and Grep surface scratch files with a [scratch] marker ---

def test_glob_lists_scratch_file_with_marker(tmp_path):
    logical = str(tmp_path / "temp_report.log")
    _write(logical, "log line", temp=True)
    real = scratch.lookup_temp(logical)
    out = _glob("temp_*.log")
    assert "[scratch]" in out
    assert real in out


def test_grep_finds_content_in_scratch_file(tmp_path):
    # Token unique to this test so no other repo file can match; path points at an
    # empty worktree dir so rg finds nothing there — the ONLY possible hit is the
    # scratch scan, which proves volet 3 (grep sees temp files).
    logical = str(tmp_path / "temp_search.txt")
    _write(logical, "alpha\nZZQNEEDLE_SCRATCH_ONLY here\nbeta", temp=True)
    out = _grep("ZZQNEEDLE_SCRATCH_ONLY", path=str(tmp_path))
    assert "ZZQNEEDLE_SCRATCH_ONLY" in out
    assert "[scratch]" in out


# --- VOLET 4: temp files survive a resume (new process, same session) ---

def test_temp_files_survive_resume_same_session(tmp_path):
    """Binding to a session persists the registry to disk; a fresh process
    (simulated by resetting module state) that rebinds the SAME session must
    still resolve the temp file."""
    scratch.set_scratch_session("resume-session-1")
    logical = str(tmp_path / "temp_persist.txt")
    _write(logical, "SURVIVES_RESUME", temp=True)

    # Simulate a brand new worker process: wipe in-memory state entirely.
    scratch._registry.clear()
    scratch._scratch_dir = None
    scratch._loaded = False
    scratch._session_id = None

    # Rebind the SAME session -> registry reloaded from persisted JSON.
    scratch.set_scratch_session("resume-session-1")
    real = scratch.lookup_temp(logical)
    assert real is not None, "resume lost the temp registry"
    assert Path(real).exists()
    assert _read(logical).count("SURVIVES_RESUME") == 1


def test_different_session_does_not_see_other_sessions_temp(tmp_path):
    scratch.set_scratch_session("session-A")
    logical = str(tmp_path / "temp_a_only.txt")
    _write(logical, "A_ONLY", temp=True)
    scratch.set_scratch_session("session-B")
    assert scratch.lookup_temp(logical) is None
