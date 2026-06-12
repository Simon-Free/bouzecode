# [desc] Conversation feature tests for the Snippet tool: ranges, errors, discard, and read-file fallback resolution.
# 
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Conversation feature tests for the Snippet tool: ranges, errors, discard, and read-file fallback resolution.</param></tool_use> [/desc]
"""Snippet behaviour through real bouzecode() conversations.

Replaces the direct snippet_tool(...) unit tests: the (mocked) model emits a
Snippet tool call and we assert on the methodology note it built
(result.state.context_state.notes) and on the tool result in the transcript.
Snippet is a meta tool, so a Methodology+Snippet batch ends the turn (1 LLM call).
"""
from __future__ import annotations

import os

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE
from bouzecode.backend.tools.state import _read_files, clear_file_state

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _snippet_call(params_xml):
    return f'<tool_use name="Snippet" id="s1">{params_xml}</tool_use>'


def _run(params_xml, user="snip"):
    mock = MockLLM([f"done.\n{METH}\n{_snippet_call(params_xml)}"])
    result = bouzecode([user], mock_llm=mock)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    sres = next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "Snippet")
    return note, sres


@pytest.fixture
def pyfile(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("def a(): pass\ndef b(): pass\ndef c(): pass\n", encoding="utf-8")
    return f


# ── ranges → methodology note ────────────────────────────────────────────────

def test_snippet_appends_labeled_range(pyfile):
    note, res = _run(f'<param name="file_path">{pyfile}</param>'
                     f'<param name="ranges">[[2, 3]]</param><param name="label">b and c</param>')
    assert "L2-3" in note and "b and c" in note
    assert "def b()" in note and "def c()" in note
    assert "def a()" not in note
    assert "appended" in res


def test_snippet_multiple_ranges(tmp_path):
    f = tmp_path / "many.py"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n", encoding="utf-8")
    note, _ = _run(f'<param name="file_path">{f}</param>'
                   f'<param name="ranges">[[1, 2], [9, 10]]</param><param name="label">edges</param>')
    assert "line1" in note and "line2" in note
    assert "line9" in note and "line10" in note
    assert "line5" not in note


def test_snippet_clamps_end_beyond_eof(tmp_path):
    f = tmp_path / "small.py"
    f.write_text("only\nthree\nlines\n", encoding="utf-8")
    note, _ = _run(f'<param name="file_path">{f}</param>'
                   f'<param name="ranges">[[1, 999]]</param><param name="label">all</param>')
    assert "only" in note and "three" in note and "lines" in note


# ── errors captured into the note (so the model sees them) ───────────────────

def test_snippet_relative_path_error_in_note():
    note, _ = _run('<param name="file_path">relative.py</param><param name="ranges">[[1, 1]]</param>')
    assert "must be absolute" in note


def test_snippet_missing_file_error_in_note(tmp_path):
    missing = tmp_path / "nope_xyz.py"
    note, _ = _run(f'<param name="file_path">{missing}</param><param name="ranges">[[1, 1]]</param>')
    assert "file not found" in note


def test_snippet_invalid_range_error_in_note(pyfile):
    note, _ = _run(f'<param name="file_path">{pyfile}</param><param name="ranges">[[5, 4]]</param>')
    assert "snippet ERROR" in note


# ── missing params → tool error, note untouched ──────────────────────────────

def test_snippet_missing_file_path_errors_without_touching_note():
    note, res = _run('<param name="ranges">[[1, 1]]</param>')
    assert res.startswith("Error:") and "file_path" in res
    assert "L1-1" not in note  # nothing was snippeted into the note


def test_snippet_missing_ranges_errors_without_touching_note():
    note, res = _run('<param name="file_path">/abs/x.py</param>')
    assert res.startswith("Error:") and "ranges" in res
    assert "snippet ERROR" not in note  # the call errored out before snippeting


# ── discard ──────────────────────────────────────────────────────────────────

def test_snippet_discard_without_ranges_adds_no_snippet():
    note, res = _run('<param name="file_path">/some/file.py</param><param name="discard">true</param>')
    assert "discarded" in res
    assert "file not found" not in note  # discard short-circuits: no read attempted
    assert "L1" not in note


def test_snippet_discard_with_ranges_still_saves(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    note, res = _run(f'<param name="file_path">{f}</param>'
                     f'<param name="ranges">[[1, 3]]</param><param name="discard">true</param>')
    assert "appended" in res
    assert "line1" in note


# ── accumulation across turns ────────────────────────────────────────────────

def test_snippet_appends_to_existing_methodology(tmp_path):
    f1 = tmp_path / "f1.py"
    f1.write_text("alpha\n", encoding="utf-8")
    f2 = tmp_path / "f2.py"
    f2.write_text("beta\n", encoding="utf-8")
    snip1 = _snippet_call(f'<param name="file_path">{f1}</param>'
                          f'<param name="ranges">[[1, 1]]</param><param name="label">one</param>')
    snip2 = _snippet_call(f'<param name="file_path">{f2}</param>'
                          f'<param name="ranges">[[1, 1]]</param><param name="label">two</param>')
    # two user turns, one Snippet each → note accumulates both; each turn ends
    # on a meta-only batch, so both responses need final text
    mock = MockLLM([f"ok.\n{METH}\n{snip1}", f"done.\n{METH}\n{snip2}"])
    result = bouzecode(["s1", "s2"], mock_llm=mock)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert "alpha" in note and "beta" in note


# ── read-file fallback resolution ────────────────────────────────────────────

@pytest.fixture
def _clean_read_files():
    clear_file_state()
    yield
    clear_file_state()


def test_snippet_auto_resolves_wrong_path_from_read_file(tmp_path, _clean_read_files):
    real = tmp_path / "agent" / "dag.py"
    real.parent.mkdir()
    real.write_text("line1\nline2\nline3\n", encoding="utf-8")
    _read_files.add(os.path.normpath(str(real)))  # precondition: file was read earlier

    wrong = tmp_path / "dag.py"  # same basename, wrong dir
    note, res = _run(f'<param name="file_path">{wrong}</param>'
                     f'<param name="ranges">[[1, 2]]</param><param name="label">fb</param>')
    assert "line1" in note and "line2" in note
    assert "auto-resolved" in note and "auto-resolved" in res


def test_snippet_ambiguous_basename_errors(tmp_path, _clean_read_files):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    fa = tmp_path / "a" / "dag.py"
    fb = tmp_path / "b" / "dag.py"
    fa.write_text("A\n", encoding="utf-8")
    fb.write_text("B\n", encoding="utf-8")
    _read_files.add(os.path.normpath(str(fa)))
    _read_files.add(os.path.normpath(str(fb)))

    wrong = tmp_path / "nowhere" / "dag.py"
    note, _ = _run(f'<param name="file_path">{wrong}</param>'
                   f'<param name="ranges">[[1, 1]]</param><param name="label">x</param>')
    assert "snippet ERROR" in note and "ambiguous" in note


def test_snippet_unknown_path_preserves_file_not_found(_clean_read_files):
    note, _ = _run('<param name="file_path">C:/totally/imaginary/nowhere.py</param>'
                   '<param name="ranges">[[1, 1]]</param>')
    assert "file not found" in note
    assert "auto-resolved" not in note
