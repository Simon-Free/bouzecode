# [desc] Tests snippet path fallback: auto-resolve from read files, ambiguous basename errors, and closest match logic
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests snippet path fallback: auto-resolve from read files, ambiguous basename errors, and closest match logic</param></tool_use> [/desc]
"""Recover from wrong snippet paths via read-file tracking.

Scenarios:
  - basename unique among read files → auto-resolve
  - basename shared but target has a discriminating suffix → pick best
  - basename shared and no suffix wins → ambiguous, error with candidates
  - basename not in read files → original error preserved
"""
from __future__ import annotations

import os

import pytest

from bouzecode.backend.context_manager import ContextState, METHODOLOGY_NOTE
from bouzecode.backend.context_manager.methodology import snippet_tool
from bouzecode.backend.tools.state import (
    _read_files,
    clear_file_state,
    find_closest_read_file,
    list_read_files_with_basename,
)


@pytest.fixture(autouse=True)
def _clean_file_state():
    clear_file_state()
    yield
    clear_file_state()


# --- find_closest_read_file pure helper -------------------------------------

def test_closest_returns_none_when_read_set_empty():
    assert find_closest_read_file("C:/any/path.py") is None


def test_closest_returns_the_only_basename_match():
    _read_files.add(os.path.normpath("C:/proj/pkg/sub/dag.py"))
    assert find_closest_read_file("C:/proj/pkg/dag.py") == os.path.normpath("C:/proj/pkg/sub/dag.py")


def test_closest_is_case_insensitive_on_basename():
    _read_files.add(os.path.normpath("C:/proj/pkg/Dag.py"))
    assert find_closest_read_file("C:/proj/pkg/DAG.py") == os.path.normpath("C:/proj/pkg/Dag.py")


def test_closest_none_when_no_basename_match():
    _read_files.add(os.path.normpath("C:/proj/pkg/other.py"))
    assert find_closest_read_file("C:/proj/pkg/dag.py") is None


def test_closest_picks_longest_common_suffix_on_ties():
    _read_files.add(os.path.normpath("C:/projA/pkg/dag.py"))
    _read_files.add(os.path.normpath("C:/projB/pkg/tools/dag.py"))
    target = "C:/projB/pkg/tools/dag.py"
    assert find_closest_read_file(target) == os.path.normpath("C:/projB/pkg/tools/dag.py")


def test_closest_returns_none_when_top_score_is_tied():
    _read_files.add(os.path.normpath("C:/projA/pkg/dag.py"))
    _read_files.add(os.path.normpath("C:/projB/pkg/dag.py"))
    assert find_closest_read_file("D:/elsewhere/dag.py") is None


def test_list_basename_returns_all_matches_sorted():
    _read_files.add(os.path.normpath("C:/a/dag.py"))
    _read_files.add(os.path.normpath("C:/b/dag.py"))
    _read_files.add(os.path.normpath("C:/c/other.py"))
    matches = list_read_files_with_basename("dag.py")
    assert matches == sorted([os.path.normpath("C:/a/dag.py"), os.path.normpath("C:/b/dag.py")])


# --- Snippet tool integration -----------------------------------------------

def test_snippet_auto_resolves_from_read_files(tmp_path):
    real = tmp_path / "agent" / "dag.py"
    real.parent.mkdir()
    real.write_text("line1\nline2\nline3\n", encoding="utf-8")
    _read_files.add(os.path.normpath(str(real)))

    wrong = str(tmp_path / "dag.py")
    gc = ContextState()
    result = snippet_tool(
        {"file_path": wrong, "ranges": [[1, 2]], "label": "fallback test"},
        {"_context_state": gc},
    )

    methodology = gc.notes[METHODOLOGY_NOTE]
    assert "line1" in methodology and "line2" in methodology
    assert "(auto-resolved from " in methodology
    assert wrong in methodology
    assert "auto-resolved" in result


def test_snippet_errors_when_basename_is_ambiguous(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    file_a = tmp_path / "a" / "dag.py"
    file_b = tmp_path / "b" / "dag.py"
    file_a.write_text("A\n", encoding="utf-8")
    file_b.write_text("B\n", encoding="utf-8")
    _read_files.add(os.path.normpath(str(file_a)))
    _read_files.add(os.path.normpath(str(file_b)))

    wrong = str(tmp_path / "nowhere" / "dag.py")
    gc = ContextState()
    snippet_tool({"file_path": wrong, "ranges": [[1, 1]], "label": "x"}, {"_context_state": gc})
    methodology = gc.notes[METHODOLOGY_NOTE]
    assert "snippet ERROR" in methodology
    assert "ambiguous" in methodology
    assert os.path.normpath(str(file_a)) in methodology
    assert os.path.normpath(str(file_b)) in methodology


def test_snippet_preserves_file_not_found_error_when_no_candidate():
    gc = ContextState()
    snippet_tool(
        {"file_path": "C:/totally/imaginary/nowhere.py", "ranges": [[1, 1]], "label": "x"},
        {"_context_state": gc},
    )
    assert "file not found" in gc.notes[METHODOLOGY_NOTE]
    assert "auto-resolved" not in gc.notes[METHODOLOGY_NOTE]


def test_snippet_success_has_no_auto_resolved_note(tmp_path):
    real = tmp_path / "ok.py"
    real.write_text("a\nb\nc\n", encoding="utf-8")
    _read_files.add(os.path.normpath(str(real)))

    gc = ContextState()
    result = snippet_tool(
        {"file_path": str(real), "ranges": [[1, 2]], "label": "ok"},
        {"_context_state": gc},
    )
    assert "auto-resolved" not in gc.notes[METHODOLOGY_NOTE]
    assert "auto-resolved" not in result
