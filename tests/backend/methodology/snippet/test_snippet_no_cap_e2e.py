# [desc] Conversation tests: a Snippet freezes everything it was asked for, whatever its size. [/desc]
"""Un Snippet fige exactement ce qu'on lui demande — il n'existe plus de plafond.

Un plafond de 200 lignes a existé ici : il rognait tout snippet plus long et
écrivait `## snippet-truncated:` dans la note. Il rendait impossible de figer une
doc de référence en un appel (la doc de référence fait 1 210 lignes) alors que les
instructions de l'agent demandent explicitement de la snippeter en entier. Ces tests
verrouillent le contrat inverse : ce qui est demandé est sauvé, intégralement.
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


def _module(path, functions: int, body_lines: int) -> int:
    """Write a python module of `functions` functions, each `body_lines` long."""
    lines = []
    for n in range(functions):
        lines.append(f"def step_{n}():")
        lines += [f"    marker_{n}_{i} = {i}" for i in range(body_lines)]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(lines)


def _snippet(params, user="garde ça"):
    """Le modèle émet un seul Snippet puis clôt. Renvoie (note, résultat d'outil)."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Snippet" id="s1">{params}</tool_use>',
        CLOSE,
    ])
    result = bouzecode([user], mock_llm=mock)
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    tool_result = next(m["content"] for m in result.messages
                       if m.get("role") == "tool" and m.get("name") == "Snippet")
    return note, tool_result


def test_a_whole_big_file_is_frozen_entirely(tmp_path):
    """Figer 400+ lignes d'un coup : la dernière ligne demandée est dans la note."""
    src = tmp_path / "big_module.py"
    total = _module(src, functions=4, body_lines=100)
    assert total > 400

    note, res = _snippet(f'<param name="file_path">{src}</param>'
                         f'<param name="ranges">[[1, {total}]]</param>'
                         f'<param name="label">tout le module</param>')

    assert "marker_0_0" in note, "le début demandé doit être sauvé"
    assert "marker_3_99" in note, "la fin demandée doit être sauvée elle aussi"
    assert "snippet-truncated" not in note, "plus aucune troncature"
    assert "ceiling" not in res, "plus aucun reproche de taille au modèle"


def test_a_huge_symbol_is_frozen_entirely(tmp_path):
    """Snippet(symbol=) sur une fonction de 400 lignes : elle passe en entier."""
    src = tmp_path / "one_huge_function.py"
    _module(src, functions=1, body_lines=400)

    note, res = _snippet(f'<param name="file_path">{src}</param>'
                         f'<param name="symbol">step_0</param>'
                         f'<param name="label">la fonction entière</param>')

    assert "marker_0_0" in note and "marker_0_399" in note
    assert "snippet-truncated" not in note
    assert "ceiling" not in res
