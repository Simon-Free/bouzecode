# [desc] Conversation tests: a missed Edit explains WHICH line diverges, and only a uniform re-indentation is auto-repaired. [/desc]
"""`old_string not found` coûte 4,6 tours par échec — le poste le plus cher mesuré
(`docs/investigations/tool_input_leniency.md`).

La mesure réfute le folklore : 0 cas d'espaces de fin, 0 homoglyphe, 0 CRLF. Ce
sont 48 % « une ligne diffère par son contenu », 18 % « indentation seule »,
34 % « deux lignes ou plus ». Donc :

- le levier est le MESSAGE : un diff ligne à ligne qui marque la ligne fautive ;
- la seule réparation tolérée est la ré-indentation UNIFORME, sous gardes ;
- les 48 % « une ligne diffère » restent un refus : appliquer l'édit sur la ligne
  du fichier supprimerait du texte que le modèle n'a jamais vu.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


def _edit_call(path, old, new):
    return (f'<tool_use name="Edit" id="e1"><param name="file_path">{path}</param>'
            f'<param name="old_string"><![CDATA[{old}]]></param>'
            f'<param name="new_string"><![CDATA[{new}]]></param></tool_use>')


def _run_edit(path, old, new):
    """Le modèle émet un seul Edit, puis clôt. Renvoie le résultat de l'outil."""
    mock = MockLLM([f"j'édite.\n{METH}\n{_edit_call(path, old, new)}", CLOSE])
    result = bouzecode(["corrige le fichier"], mock_llm=mock)
    return next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "Edit")


# ── la seule réparation tolérée : décalage uniforme ──────────────────────────

def test_edit_repairs_a_uniformly_over_indented_old_string(tmp_path):
    """Le bloc envoyé est décalé de 2 colonnes partout : l'édit s'applique à l'indentation du fichier."""
    f = tmp_path / "temp_close.py"
    f.write_text(
        "def run():\n"
        "    try:\n"
        "        work()\n"
        "        finally_marker()\n",
        encoding="utf-8")

    res = _run_edit(f,
                    "          work()\n          finally_marker()",
                    "          work()\n          log('done')\n          finally_marker()")

    assert f.read_text(encoding="utf-8") == (
        "def run():\n"
        "    try:\n"
        "        work()\n"
        "        log('done')\n"
        "        finally_marker()\n")
    assert "re-indented automatically (-2 columns" in res


# ── ce qui doit rester un refus ──────────────────────────────────────────────

def test_edit_refuses_a_non_uniform_shift_and_leaves_the_file_alone(tmp_path):
    """Une seule ligne décalée différemment : refus. En Python, l'indentation EST la sémantique."""
    f = tmp_path / "temp_shift.py"
    original = "def run():\n        alpha()\n        beta()\n        gamma()\n"
    f.write_text(original, encoding="utf-8")

    res = _run_edit(f,
                    "          alpha()\n          beta()\n         gamma()",
                    "          alpha()\n          delta()\n         gamma()")

    assert f.read_text(encoding="utf-8") == original
    assert res.startswith("Error:") and "old_string not found" in res


def test_edit_refuses_when_the_same_block_exists_at_two_indentations(tmp_path):
    """Deux candidats à indentation près : l'outil refuse de choisir, le fichier reste intact."""
    f = tmp_path / "temp_twice.py"
    original = (
        "def a():\n"
        "    do()\n"
        "    done()\n"
        "def b():\n"
        "        do()\n"
        "        done()\n")
    f.write_text(original, encoding="utf-8")

    res = _run_edit(f, "      do()\n      done()", "      do()\n      extra()\n      done()")

    assert f.read_text(encoding="utf-8") == original
    assert res.startswith("Error:")


def test_edit_refuses_when_one_line_differs_in_content(tmp_path):
    """Cas réel du corpus : le fichier porte un commentaire que le modèle n'a pas vu — réparer le supprimerait."""
    f = tmp_path / "temp_ddl.py"
    original = (
        "def setup():\n"
        "    svc = BouzecodeSessionService(kind=\"rec\")\n"
        "    # Ensure schema exists and is clean — skip if DDL fails (permissions)\n"
        "    conn = svc.get_connection(autocommit=True)\n")
    f.write_text(original, encoding="utf-8")

    res = _run_edit(f,
                    "    svc = BouzecodeSessionService(kind=\"rec\")\n"
                    "    # Ensure schema exists and is clean\n"
                    "    conn = svc.get_connection(autocommit=True)",
                    "    conn = None")

    # Le fragment « — skip if DDL fails » est toujours là : rien n'a été détruit.
    assert f.read_text(encoding="utf-8") == original
    assert "skip if DDL fails" in res  # le message MONTRE la vraie ligne


# ── le message : un diff, pas un déversement ─────────────────────────────────

def test_edit_error_marks_the_diverging_line_with_a_diff(tmp_path):
    """Le message pointe la ligne fautive avec ≠ et son numéro, au lieu de 20 lignes numérotées à éplucher."""
    f = tmp_path / "temp_diff.py"
    f.write_text(
        "import os\n"
        "def setup():\n"
        "    svc = Service(kind=\"rec\")\n"
        "    # Ensure schema exists and is clean — skip if DDL fails (permissions)\n"
        "    conn = svc.get_connection(autocommit=True)\n",
        encoding="utf-8")

    res = _run_edit(f,
                    "    svc = Service(kind=\"rec\")\n"
                    "    # Ensure schema exists and is clean\n"
                    "    conn = svc.get_connection(autocommit=True)",
                    "    conn = None")

    assert "≠" in res
    assert "1 line(s) out of 3 differ" in res
    assert "≠     4  + " in res  # la ligne 4 du fichier est celle qui diverge


def test_edit_error_on_a_single_line_old_string_is_never_the_bare_sentence(tmp_path):
    """Un old_string d'UNE ligne obtient lui aussi son diff — c'est 19 % des échecs jusqu'ici muets."""
    f = tmp_path / "temp_single.py"
    f.write_text(
        "def total(items):\n"
        "    result = compute_total(items, discount=True)\n"
        "    return result\n",
        encoding="utf-8")

    res = _run_edit(f,
                    "    result = compute_total(items, discount=False)\n",
                    "    result = 0\n")

    assert "ensure EXACT match" not in res  # l'ancienne phrase nue a disparu
    assert "≠" in res and "similarity" in res


def test_edit_error_without_any_close_block_still_quotes_a_similarity(tmp_path):
    """Quand rien ne ressemble, l'outil chiffre quand même l'écart et dit de relire — jamais le silence."""
    f = tmp_path / "temp_nomatch.py"
    original = "alpha\nbeta\ngamma\n"
    f.write_text(original, encoding="utf-8")

    res = _run_edit(f, "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", "QQQ")

    assert f.read_text(encoding="utf-8") == original
    assert "best similarity" in res
    assert "Do NOT re-send the same old_string" in res
