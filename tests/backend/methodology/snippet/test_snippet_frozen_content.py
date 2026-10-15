# [desc] Test e2e vérifiant qu'un Snippet sur un fichier lu puis supprimé fige le contenu au lieu d'échouer [/desc]
"""A Snippet must never lose content the agent already read.

Real-world failure (session 299279a7, turn 22): a %TEMP% script was read
successfully, got reaped by the OS, and the following Snippet answered
``## snippet ERROR: ... file not found ... Nothing was saved.`` The agent then
decided to *retype* the file content into the methodology prose — which is the
expensive behaviour we are trying to kill.

Staging note: the read-file registry (`backend/tools/state.py`) lives in
module-level globals, so it survives across two `bouzecode()` calls in the same
process. That lets us reproduce the exact sequence without a shell tool:
read (session 1) → delete → snippet (session 2).
"""
from __future__ import annotations

import os

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE
from bouzecode.backend.tools.state import clear_file_state

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


@pytest.fixture
def _clean_read_files():
    clear_file_state()
    yield
    clear_file_state()


def _read_then_delete(path):
    """Session 1: the agent really reads the file. Then the file disappears."""
    mock = MockLLM([
        f'lecture.\n{METH}\n'
        f'<tool_use name="Read" id="r1"><param name="file_path">{path}</param></tool_use>',
        CLOSE,
    ])
    bouzecode(["lis ce fichier"], mock_llm=mock)
    os.remove(path)
    assert not os.path.exists(path)


def _snippet_session(params_xml):
    """Session 2 (same process): the agent snippets the now-deleted file."""
    mock = MockLLM([
        f'done.\n{METH}\n<tool_use name="Snippet" id="s1">{params_xml}</tool_use>',
        CLOSE,
    ])
    result = bouzecode(["note ce que tu as lu"], mock_llm=mock)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    sres = next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "Snippet")
    return note, sres


def test_ranges_snippet_survives_a_file_deleted_after_being_read(tmp_path, _clean_read_files):
    """Un fichier lu puis supprimé se snippette quand même : le contenu lu est figé, pas perdu."""
    f = tmp_path / "rm_q8.py"
    f.write_text("select 1\nfrom d_jour\nwhere annee = 2025\n", encoding="utf-8")
    _read_then_delete(f)

    note, res = _snippet_session(
        f'<param name="file_path">{f}</param>'
        f'<param name="ranges">[[1, 3]]</param><param name="label">requete</param>')

    assert "file not found" not in note
    assert "Nothing was saved" not in res
    assert "select 1" in note and "where annee = 2025" in note
    assert "frozen" in note


def test_symbol_snippet_survives_a_file_deleted_after_being_read(tmp_path, _clean_read_files):
    """Un snippet par symbole tient aussi quand le fichier a disparu du disque après lecture."""
    f = tmp_path / "gone_module.py"
    f.write_text(
        "import os\n\n\ndef keeper(x):\n    return x + 1\n\n\ndef other():\n    return 0\n",
        encoding="utf-8")
    _read_then_delete(f)

    note, res = _snippet_session(
        f'<param name="file_path">{f}</param><param name="symbol">keeper</param>')

    assert "file not found" not in note
    assert "Nothing was saved" not in res
    assert "def keeper(x)" in note and "return x + 1" in note
    assert "def other()" not in note


def test_never_read_missing_file_still_reports_not_found(tmp_path, _clean_read_files):
    """Un fichier jamais lu et absent garde son « file not found » : le repli n'invente rien."""
    ghost = tmp_path / "never_read.py"
    note, _ = _snippet_session(
        f'<param name="file_path">{ghost}</param><param name="ranges">[[1, 1]]</param>')

    assert "file not found" in note
    assert "frozen" not in note
