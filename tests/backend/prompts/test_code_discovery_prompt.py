# [desc] Tests that code discovery guidance lives in the default code-agent profile. [/desc]
"""Code discovery guidance now lives in the default (code) agent profile, layered on
the agnostic noyau at depth 0 by dispatch — not in the shared base prompt."""

from bouzecode.backend.core.context import build_system_prompt
from bouzecode.backend.profiles import load_system_profiles


def test_code_discovery_guidance_in_default_profile():
    extra = load_system_profiles()["default"].system_prompt_extra
    assert "Découverte de code" in extra or "code discovery" in extra.lower()
    # L'échelle ne cite QUE des outils réellement offerts : GetFolderDescription en a été
    # retiré (obsolète, zéro appel en 17 897 tours) — cf. test_prompt_registry_conformity.
    assert "GetFolderDescription" not in extra
    assert "Glob" in extra
    assert "Grep" in extra
    assert "Read(symbol=" in extra
    # Separation of concerns: not in the agnostic noyau.
    assert "Read(symbol=" not in build_system_prompt({})


def test_findcode_before_grep_ordering():
    """FindCode AVANT le grep.

    Cas réel : un agent `coder` au premier tour a lancé 3 Grep larges (patterns vagues
    sur la racine du repo) = ~74K chars de résultats, tous jetés au tour suivant. L'outil
    de localisation doit donc venir en tête de l'échelle, et le Grep qui reste prescrit
    doit être borné, réservé à un texte exact.
    """
    extra = load_system_profiles()["default"].system_prompt_extra
    assert "~0 token de sortie" not in extra
    ladder = next(line for line in extra.splitlines() if "Découverte de code" in line)
    assert ladder.index("FindCode") < ladder.index("Grep"), (
        "l'échelle doit citer FindCode AVANT le grep")
    assert "load=true" in ladder
    assert 'output_mode="files_with_matches"' in ladder
    # Les outils de cartes générées par LLM ont été retirés : plus aucune mention.
    assert "AgentsMap" not in extra and "SymbolMap" not in extra
