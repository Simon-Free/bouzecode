# [desc] Le delta Methodology du tour est affiché en clair dans le terminal, comme le plan. [/desc]
"""L'utilisateur doit lire le texte ajouté à la note Methodology ce tour-ci,
pas seulement « ✓ Methodology → 1 lines (35 chars) »."""
from __future__ import annotations

from bouzecode.ui.tool_display import print_tool_end, print_tool_start


def test_methodology_start_shows_the_whole_delta_of_the_turn(capsys):
    delta = ("- Fait : le test X échoue sur `parse()`\n"
             "- Décision : corriger le parseur, car la cause est là\n"
             "- Prochaine étape : relancer test_parse.py — " + "détail " * 30)
    print_tool_start("Methodology", {"content": delta}, verbose=False)
    out = capsys.readouterr().out
    assert "Méthodologie" in out
    assert "Décision : corriger le parseur" in out
    # le texte entier, pas la version tronquée à 100 caractères de la ligne d'appel
    assert "détail détail" in out.split("Méthodologie", 1)[1]
    assert "relancer test_parse.py" in out


def test_methodology_end_replaces_generic_summary(capsys):
    print_tool_end("Methodology", "methodology append: ok", verbose=False, duration=0.0)
    out = capsys.readouterr().out
    assert "lines (" not in out
    assert "Methodology" in out


def test_methodology_end_still_shows_a_failure(capsys):
    print_tool_end("Methodology", "Error: content manquant", verbose=False)
    out = capsys.readouterr().out
    assert "Error: content manquant" in out


def test_methodology_without_content_does_not_crash(capsys):
    print_tool_start("Methodology", {}, verbose=False)
    out = capsys.readouterr().out
    assert "Méthodologie" not in out
