# [desc] Unit tests for the read-file matcher behind the snippet path fallback (find_closest_read_file / list_read_files_with_basename). [/desc]
"""Path matching rules used to recover from a wrong Snippet path.

Only the pure matcher lives here: given the set of files the agent has read,
which one does a mistyped path resolve to? The tie-breaking rules (basename
match, case-insensitivity, longest common suffix, refusal on a tie) are
per-branch invariants of a string algorithm — a conversation can reach a few of
them but not each one, so they stay unit tests.

The end-user behaviour built on top of this matcher — "the agent snippets a
wrong path and gets rescued / told it is ambiguous / told the file is unknown" —
is covered as a real conversation in test_snippet_e2e.py
(test_snippet_auto_resolves_wrong_path_from_read_file,
 test_snippet_ambiguous_basename_errors,
 test_snippet_unknown_path_preserves_file_not_found,
 test_snippet_on_the_right_path_mentions_no_fallback).
"""
from __future__ import annotations

import os

import pytest

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


def test_closest_returns_none_when_read_set_empty():
    """Sans aucune lecture enregistrée, il n'y a rien vers quoi rattraper un chemin."""
    assert find_closest_read_file("C:/any/path.py") is None


def test_closest_returns_the_only_basename_match():
    """Un seul fichier lu porte ce nom : c'est lui, quel que soit le dossier indiqué."""
    _read_files.add(os.path.normpath("C:/proj/pkg/sub/dag.py"))
    assert find_closest_read_file("C:/proj/pkg/dag.py") == os.path.normpath("C:/proj/pkg/sub/dag.py")


def test_closest_is_case_insensitive_on_basename():
    """La casse du nom de fichier n'empêche pas le rattrapage."""
    _read_files.add(os.path.normpath("C:/proj/pkg/Dag.py"))
    assert find_closest_read_file("C:/proj/pkg/DAG.py") == os.path.normpath("C:/proj/pkg/Dag.py")


def test_closest_none_when_no_basename_match():
    """Aucun fichier lu ne porte ce nom : pas de rattrapage inventé."""
    _read_files.add(os.path.normpath("C:/proj/pkg/other.py"))
    assert find_closest_read_file("C:/proj/pkg/dag.py") is None


def test_closest_picks_longest_common_suffix_on_ties():
    """À nom égal, le candidat qui partage le plus long chemin de fin l'emporte."""
    _read_files.add(os.path.normpath("C:/projA/pkg/dag.py"))
    _read_files.add(os.path.normpath("C:/projB/pkg/tools/dag.py"))
    target = "C:/projB/pkg/tools/dag.py"
    assert find_closest_read_file(target) == os.path.normpath("C:/projB/pkg/tools/dag.py")


def test_closest_returns_none_when_top_score_is_tied():
    """Deux candidats à égalité parfaite : le matcher refuse de trancher."""
    _read_files.add(os.path.normpath("C:/projA/pkg/dag.py"))
    _read_files.add(os.path.normpath("C:/projB/pkg/dag.py"))
    assert find_closest_read_file("D:/elsewhere/dag.py") is None


def test_list_basename_returns_all_matches_sorted():
    """La liste des candidats homonymes est complète et ordonnée, pour un message d'erreur stable."""
    _read_files.add(os.path.normpath("C:/a/dag.py"))
    _read_files.add(os.path.normpath("C:/b/dag.py"))
    _read_files.add(os.path.normpath("C:/c/other.py"))
    matches = list_read_files_with_basename("dag.py")
    assert matches == sorted([os.path.normpath("C:/a/dag.py"), os.path.normpath("C:/b/dag.py")])
