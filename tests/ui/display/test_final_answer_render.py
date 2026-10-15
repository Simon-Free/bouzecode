# [desc] Tests that FinalAnswer renders as rich Markdown once delivered, and that a refused close prints one dim line instead of the answer. [/desc]
"""FinalAnswer is shown to the terminal user as rich text (Markdown), the way an assistant
message is — not as the dim '✓ FinalAnswer → N lines' line. It is rendered when its RESULT
arrives: a close the harness refused (children still active, missing field…) must not print
the whole answer in the main thread (session B4, 2026-10-14)."""
from __future__ import annotations

from bouzecode.ui.tool_display import print_tool_end, print_tool_start

LIVREE = "Session closing — final answer delivered:\n"


def test_final_answer_start_prints_nothing_before_the_outcome(capsys):
    """Le texte n'apparaît pas à l'annonce de l'appel : la clôture peut encore être refusée."""
    print_tool_start("FinalAnswer", {"answer": "# Résultat\nTâche **terminée**."}, verbose=False)
    assert capsys.readouterr().out == ""


def test_delivered_final_answer_renders_markdown_content(capsys):
    """Clôture acceptée : la réponse livrée s'affiche en Markdown, sans résumé générique."""
    answer = "# Résultat\nTâche **terminée**."
    print_tool_end("FinalAnswer", LIVREE + answer, verbose=False, inputs={"answer": answer})
    out = capsys.readouterr().out
    assert "Résultat" in out and "terminée" in out
    assert "→" not in out and "lines (" not in out


def test_delivered_answer_shows_the_harness_warnings(capsys):
    """Le texte affiché est celui LIVRÉ (avec l'aveu ajouté par le harnais), pas l'appel brut."""
    livre = "Fait.\n\n⚠️ Clôture forcée alors que des sous-agents étaient encore actifs"
    print_tool_end("FinalAnswer", LIVREE + livre, verbose=False, inputs={"answer": "Fait."})
    assert "Clôture forcée" in capsys.readouterr().out


def test_refused_close_prints_one_dim_line_not_the_answer(capsys):
    """Clôture refusée (enfants actifs) : une seule ligne, le rapport refusé n'est pas imprimé."""
    refus = ("CLÔTURE DIFFÉRÉE — 3 sous-agent(s) encore actif(s) : le harnais les a attendus "
             "pour toi. Leurs comptes rendus :\n\n### t1 (alpha)\nrapport alpha")
    print_tool_end("FinalAnswer", refus, verbose=False,
                   inputs={"answer": "1. Résumé — je reprendrai à la fin de chacun d'eux"})
    out = capsys.readouterr().out
    assert "Résumé" not in out and "rapport alpha" not in out
    assert "3 sous-agent(s) encore actif(s)" in out
    assert len(out.strip().splitlines()) == 1


def test_final_answer_preserves_tool_markup_verbatim(capsys):
    """Un `<param ...>` littéral dans la réponse n'est pas avalé par le Markdown."""
    answer = "Appelle `<param name=x>`"
    print_tool_end("FinalAnswer", LIVREE + answer, verbose=False, inputs={"answer": answer})
    assert "param" in capsys.readouterr().out


def test_final_answer_without_result_falls_back_to_its_answer(capsys):
    """Rejeu d'une session sans résultat : on montre la réponse telle qu'appelée."""
    print_tool_end("FinalAnswer", "", verbose=False, inputs={"answer": "Done."})
    assert "Done." in capsys.readouterr().out
