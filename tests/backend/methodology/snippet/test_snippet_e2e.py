# [desc] Conversation feature tests for the Snippet tool: ranges, errors, discard, and read-file fallback resolution. [/desc]
"""Snippet behaviour through real bouzecode() conversations.

Replaces the direct snippet_tool(...) unit tests: the (mocked) model emits a
Snippet tool call and we assert on the methodology note it built
(result.state.context_state.notes) and on the tool result in the transcript.

Turn shape: Methodology + Snippet is a *meta-only* batch, which no longer closes
the session (see loop_turn.META_ONLY_TOOLS) — the loop nudges the model to keep
going. So every scenario needs a second, tool-call-free reply to close the turn.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE
from bouzecode.backend.context_manager.methodology import (
    reconstruct_methodology_from_timeline,
)
from bouzecode.backend.tools.state import clear_file_state

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


def _snippet_call(params_xml):
    return f'<tool_use name="Snippet" id="s1">{params_xml}</tool_use>'


def _run(params_xml, user="snip"):
    mock = MockLLM([f"done.\n{METH}\n{_snippet_call(params_xml)}", CLOSE])
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
    """Un Snippet d'une plage de lignes atterrit étiqueté dans la note, sans les lignes voisines."""
    note, res = _run(f'<param name="file_path">{pyfile}</param>'
                     f'<param name="ranges">[[2, 3]]</param><param name="label">b and c</param>')
    assert "L2-3" in note and "b and c" in note
    assert "def b()" in note and "def c()" in note
    assert "def a()" not in note
    assert "appended" in res


def test_snippet_multiple_ranges(tmp_path):
    """Plusieurs plages demandées en un seul appel sont toutes recopiées dans la note."""
    f = tmp_path / "many.py"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n", encoding="utf-8")
    note, _ = _run(f'<param name="file_path">{f}</param>'
                   f'<param name="ranges">[[1, 2], [9, 10]]</param><param name="label">edges</param>')
    assert "line1" in note and "line2" in note
    assert "line9" in note and "line10" in note
    assert "line5" not in note


def test_snippet_clamps_end_beyond_eof(tmp_path):
    """Une plage qui déborde la fin du fichier est ramenée à la dernière ligne au lieu d'échouer."""
    f = tmp_path / "small.py"
    f.write_text("only\nthree\nlines\n", encoding="utf-8")
    note, _ = _run(f'<param name="file_path">{f}</param>'
                   f'<param name="ranges">[[1, 999]]</param><param name="label">all</param>')
    assert "only" in note and "three" in note and "lines" in note


# ── errors captured into the note (so the model sees them) ───────────────────

def test_snippet_relative_path_error_in_note():
    """Un chemin relatif est refusé et l'erreur est écrite dans la note pour que le modèle la voie."""
    note, _ = _run('<param name="file_path">relative.py</param><param name="ranges">[[1, 1]]</param>')
    assert "must be absolute" in note


def test_snippet_missing_file_error_in_note(tmp_path):
    """Snippeter un fichier inexistant laisse un « file not found » visible dans la note."""
    missing = tmp_path / "nope_xyz.py"
    note, _ = _run(f'<param name="file_path">{missing}</param><param name="ranges">[[1, 1]]</param>')
    assert "file not found" in note


def test_snippet_invalid_range_error_in_note(pyfile):
    """Une plage inversée est signalée comme erreur de snippet dans la note."""
    note, _ = _run(f'<param name="file_path">{pyfile}</param><param name="ranges">[[5, 4]]</param>')
    assert "snippet ERROR" in note


# ── missing params → tool error, note untouched ──────────────────────────────

def test_snippet_missing_file_path_errors_without_touching_note():
    """Un Snippet sans file_path renvoie une erreur d'outil et laisse la note intacte."""
    note, res = _run('<param name="ranges">[[1, 1]]</param>')
    assert res.startswith("Error:") and "file_path" in res
    assert "L1-1" not in note  # nothing was snippeted into the note


def test_snippet_missing_ranges_errors_without_touching_note():
    """Un Snippet sans ranges renvoie une erreur d'outil et laisse la note intacte."""
    note, res = _run('<param name="file_path">/abs/x.py</param>')
    assert res.startswith("Error:") and "ranges" in res
    assert "snippet ERROR" not in note  # the call errored out before snippeting


# ── discard ──────────────────────────────────────────────────────────────────

def test_snippet_discard_without_ranges_adds_no_snippet():
    """Snippet(discard=true) sans plage acquitte la lecture sans rien ajouter à la note."""
    note, res = _run('<param name="file_path">/some/file.py</param><param name="discard">true</param>')
    assert "discarded" in res
    assert "file not found" not in note  # discard short-circuits: no read attempted
    assert "L1" not in note


def test_snippet_discard_with_ranges_still_saves(tmp_path):
    """Snippet(discard=true) avec des plages sauvegarde quand même les lignes demandées."""
    f = tmp_path / "code.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    note, res = _run(f'<param name="file_path">{f}</param>'
                     f'<param name="ranges">[[1, 3]]</param><param name="discard">true</param>')
    assert "appended" in res
    assert "line1" in note


# ── accumulation across turns ────────────────────────────────────────────────

def test_snippet_appends_to_existing_methodology(tmp_path):
    """Deux Snippets sur deux tours s'accumulent dans la même note au lieu de s'écraser."""
    f1 = tmp_path / "f1.py"
    f1.write_text("alpha\n", encoding="utf-8")
    f2 = tmp_path / "f2.py"
    f2.write_text("beta\n", encoding="utf-8")
    snip1 = _snippet_call(f'<param name="file_path">{f1}</param>'
                          f'<param name="ranges">[[1, 1]]</param><param name="label">one</param>')
    snip2 = _snippet_call(f'<param name="file_path">{f2}</param>'
                          f'<param name="ranges">[[1, 1]]</param><param name="label">two</param>')
    # two user turns, one Snippet each → note accumulates both; a meta-only batch
    # does not close, so each user turn needs its own tool-call-free reply
    mock = MockLLM([f"ok.\n{METH}\n{snip1}", CLOSE, f"done.\n{METH}\n{snip2}", CLOSE])
    result = bouzecode(["s1", "s2"], mock_llm=mock)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert "alpha" in note and "beta" in note


# ── timeline journal ─────────────────────────────────────────────────────────

def test_snippet_is_journalled_in_the_notes_timeline(pyfile):
    """Chaque Snippet laisse une entrée datée du tour courant dans le journal de la note."""
    mock = MockLLM([
        f'done.\n{METH}\n' + _snippet_call(f'<param name="file_path">{pyfile}</param>'
                                           f'<param name="ranges">[[1, 1]]</param>'),
        CLOSE,
    ])
    result = bouzecode(["snip"], mock_llm=mock)
    timeline = result.state.notes_timeline
    assert timeline, "the Snippet turn must be journalled"
    # Le journal ne stocke QUE des deltas (l'instantané complet par tour faisait grossir la
    # session en O(tours²)). On observe donc le contenu là où il vit désormais : dans le delta
    # du tour, et dans la note RECONSTITUÉE en repliant le journal — ce que fait le code qui
    # sert un tour à l'affichage.
    assert any("def a()" in str(e.get("delta", "")) for e in timeline)
    assert "def a()" in reconstruct_methodology_from_timeline(timeline)
    assert all(isinstance(e.get("turn"), int) for e in timeline)


# ── read-file fallback resolution ────────────────────────────────────────────
#
# The precondition ("the agent read this file earlier") is produced by a real
# Read tool call in turn 1 — no direct poking at the read-file tracker.

@pytest.fixture
def _clean_read_files():
    clear_file_state()
    yield
    clear_file_state()


def _read_call(path, i=1):
    return f'<tool_use name="Read" id="r{i}"><param name="file_path">{path}</param></tool_use>'


def _run_after_reads(read_paths, snippet_params):
    """Turn 1: the agent reads files. Turn 2: it snippets. Turn 3: it closes."""
    reads = "\n".join(_read_call(p, i) for i, p in enumerate(read_paths, start=1))
    mock = MockLLM([
        f"lecture.\n{METH}\n{reads}",
        f"done.\n{METH}\n{_snippet_call(snippet_params)}",
        CLOSE,
    ])
    result = bouzecode(["regarde puis note"], mock_llm=mock)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    sres = next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "Snippet")
    return note, sres


def test_snippet_auto_resolves_wrong_path_from_read_file(tmp_path, _clean_read_files):
    """Un chemin erroné est rattrapé sur le fichier déjà lu qui porte le même nom, et l'agent en est informé."""
    real = tmp_path / "agent" / "dag.py"
    real.parent.mkdir()
    real.write_text("line1\nline2\nline3\n", encoding="utf-8")

    wrong = tmp_path / "dag.py"  # same basename, wrong dir
    note, res = _run_after_reads(
        [real],
        f'<param name="file_path">{wrong}</param>'
        f'<param name="ranges">[[1, 2]]</param><param name="label">fb</param>')
    assert "line1" in note and "line2" in note
    assert "auto-resolved" in note and "auto-resolved" in res


def test_snippet_ambiguous_basename_errors(tmp_path, _clean_read_files):
    """Quand deux fichiers lus portent le même nom, le rattrapage refuse de choisir et liste les candidats."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    fa = tmp_path / "a" / "dag.py"
    fb = tmp_path / "b" / "dag.py"
    fa.write_text("A\n", encoding="utf-8")
    fb.write_text("B\n", encoding="utf-8")

    wrong = tmp_path / "nowhere" / "dag.py"
    note, _ = _run_after_reads(
        [fa, fb],
        f'<param name="file_path">{wrong}</param>'
        f'<param name="ranges">[[1, 1]]</param><param name="label">x</param>')
    assert "snippet ERROR" in note and "ambiguous" in note
    assert str(fa) in note or os.path.normpath(str(fa)) in note


def test_snippet_unknown_path_preserves_file_not_found(_clean_read_files):
    """Un chemin inconnu d'aucune lecture garde l'erreur d'origine, sans rattrapage silencieux."""
    note, _ = _run('<param name="file_path">C:/totally/imaginary/nowhere.py</param>'
                   '<param name="ranges">[[1, 1]]</param>')
    assert "file not found" in note
    assert "auto-resolved" not in note


def test_snippet_on_the_right_path_mentions_no_fallback(tmp_path, _clean_read_files):
    """Quand le chemin est bon, aucun message de rattrapage ne vient polluer la note ni la réponse."""
    real = tmp_path / "ok.py"
    real.write_text("a\nb\nc\n", encoding="utf-8")
    note, res = _run_after_reads(
        [real],
        f'<param name="file_path">{real}</param>'
        f'<param name="ranges">[[1, 2]]</param><param name="label">ok</param>')
    assert "a" in note and "auto-resolved" not in note
    assert "auto-resolved" not in res
