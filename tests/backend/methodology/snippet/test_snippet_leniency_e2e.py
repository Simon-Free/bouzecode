# [desc] Conversation tests: a Snippet without `ranges` saves the whole result, and never guesses. [/desc]
"""L'agent nomme ce qu'il veut garder et oublie les numéros de ligne.

C'est le cas mesuré 390 fois sur 390 (`docs/investigations/tool_input_leniency.md`) :
`ranges` n'est pas malformé, il est ABSENT. Le contenu visé est déjà sur le fil et
sa longueur est connue, donc refuser ne coûte qu'un aller-retour.

Ce que ces tests fixent :
- `ranges` absent -> TOUT est sauvé, quelle que soit la taille, et le résultat le dit.
  Un plafond de 60 lignes refusait au-delà : « garde tout » était alors inexprimable
  pour une doc de référence, ce que les instructions de l'agent exigent pourtant ;
- tool_id mort -> refus, avec la liste des ids encore sur le fil ;
- fichier disparu depuis la lecture -> message d'erreur, pas d'exception.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE
from bouzecode.backend.tools.state import clear_file_state

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


@pytest.fixture(autouse=True)
def _clean_read_files():
    clear_file_state()
    yield
    clear_file_state()


def _run(snippet_params, user="note ça"):
    """Le modèle émet un seul Snippet, puis clôt. Renvoie (note, résultat de l'outil)."""
    mock = MockLLM([
        f'done.\n{METH}\n<tool_use name="Snippet" id="s1">{snippet_params}</tool_use>',
        CLOSE,
    ])
    result = bouzecode([user], mock_llm=mock)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    tool_result = next(m["content"] for m in result.messages
                       if m.get("role") == "tool" and m.get("name") == "Snippet")
    return note, tool_result


# ── ranges absent : le sur-ensemble borné ────────────────────────────────────

def test_snippet_without_ranges_saves_a_short_file_whole(tmp_path):
    """Appel réel du corpus : file_path + label, sans ranges — le fichier court est sauvé en entier."""
    f = tmp_path / "schemas.py"
    f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    note, res = _run(f'<param name="file_path">{f}</param>'
                     f'<param name="label">Définitions des schémas d\'outils</param>')

    assert "alpha" in note and "beta" in note and "gamma" in note
    assert "whole result saved (3 lines)" in res
    assert "ranges=[[a, b]]" in res  # on lui dit comment viser plus court


def test_snippet_without_ranges_saves_a_short_tool_result_whole():
    """Appel réel du corpus : tool_id + label, sans ranges — le résultat court est sauvé en entier."""
    bash = ('<tool_use name="Bash" id="b1">'
            '<param name="command">echo alpha; echo beta</param></tool_use>')
    mock = MockLLM([
        f"lecture.\n{METH}\n{bash}",
        f'done.\n{METH}\n<tool_use name="Snippet" id="s1">'
        f'<param name="tool_id">b1</param>'
        f'<param name="label">git show --stat 3ee2abb</param></tool_use>',
        CLOSE,
    ])
    result = bouzecode(["lance et note"], mock_llm=mock)

    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    res = next(m["content"] for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "Snippet")
    assert "alpha" in note and "beta" in note
    assert "whole result saved" in res


def test_snippet_without_ranges_saves_a_long_file_whole(tmp_path):
    """Sans `ranges`, un long fichier est sauvé EN ENTIER : c'est ainsi qu'on dit « garde tout »."""
    f = tmp_path / "gros.py"
    f.write_text("\n".join(f"ligne {i}" for i in range(1, 301)) + "\n", encoding="utf-8")

    note, res = _run(f'<param name="file_path">{f}</param>'
                     f'<param name="label">tout le module</param>')

    assert "ligne 1" in note and "ligne 42" in note and "ligne 300" in note
    assert "whole result saved" in res and "300 lines" in res


def test_snippet_without_ranges_nor_label_still_saves_everything(tmp_path):
    """L'absence de label ne change rien : le contenu visé est sauvé, jamais jeté en silence."""
    f = tmp_path / "gros.py"
    f.write_text("\n".join(f"ligne {i}" for i in range(1, 301)) + "\n", encoding="utf-8")

    note, res = _run(f'<param name="file_path">{f}</param>')

    assert "ligne 42" in note and "ligne 300" in note
    assert "whole result saved" in res


# ── ce qui doit rester un refus ──────────────────────────────────────────────

def test_snippet_on_a_dead_tool_id_refuses_and_lists_the_live_ids():
    """Un tool_id absent du fil n'est jamais rattrapé sur un autre résultat : refus + liste des ids vivants."""
    bash = ('<tool_use name="Bash" id="b3">'
            '<param name="command">echo bonjour</param></tool_use>')
    mock = MockLLM([
        f"lecture.\n{METH}\n{bash}",
        f'done.\n{METH}\n<tool_use name="Snippet" id="s1">'
        f'<param name="tool_id">net1</param>'
        f'<param name="ranges">[[1, 2]]</param></tool_use>',
        CLOSE,
    ])
    result = bouzecode(["lance et note"], mock_llm=mock)

    res = next(m["content"] for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "Snippet")
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert res.startswith("Error:") and "net1" in res
    assert "b3" in res  # les ids réellement présents sont énumérés
    assert "bonjour" not in note  # surtout : rien d'un AUTRE résultat n'a été sauvé


# ── le crash mesuré : le fichier de repli n'existe plus ──────────────────────

def test_snippet_on_a_deleted_file_reports_it_instead_of_crashing(tmp_path):
    """Le fichier lu plus tôt a été supprimé entre-temps : Snippet le dit, au lieu de lever FileNotFoundError."""
    log = tmp_path / "temp_run.log"
    log.write_text("premiere\ndeuxieme\ntroisieme\n", encoding="utf-8")

    # Session 1 : l'agent lit le log, il entre donc au registre des fichiers lus.
    read = f'<tool_use name="Read" id="r1"><param name="file_path">{log}</param></tool_use>'
    bouzecode(["lis le log"], mock_llm=MockLLM([f"lecture.\n{METH}\n{read}", CLOSE]))

    # Le log disparaît pour de vrai (temp nettoyé, worktree reapé) — aucun patch.
    log.unlink()

    # Session 2 : l'agent snippette un chemin de même basename, donc le repli
    # « fichier déjà lu » se déclenche… sur un chemin qui n'existe plus.
    disparu = tmp_path / "ailleurs" / "temp_run.log"
    note, res = _run(f'<param name="file_path">{disparu}</param>'
                     f'<param name="ranges">[[1, 3]]</param>')

    assert "snippet ERROR" in note and "gone from disk" in note
    assert "premiere" not in note  # rien n'a été inventé
    assert "Error executing Snippet" not in res
    assert "FileNotFoundError" not in res


# ── réparations non ambiguës du tool_id ──────────────────────────────────────

def test_snippet_tool_id_carrying_the_whole_marker_is_routed_to_file_path(tmp_path):
    """Le modèle recopie le marqueur entier (« file_path=C:\\... ») : le préfixe est retiré, pas deviné."""
    f = tmp_path / "code.py"
    f.write_text("un\ndeux\n", encoding="utf-8")

    note, res = _run(f'<param name="tool_id">file_path={f}</param>'
                     f'<param name="ranges">[[1, 2]]</param>')

    assert "un" in note and "deux" in note
    assert "names a FILE" in res
