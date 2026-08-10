"""Garde de doc : la méthodo de test système doit contenir la règle
'fixtures dérivées du réel, jamais inventées'. Ce test protège la section 6
du prompt fast-testing (et son résumé côté coder) contre une suppression
silencieuse — il n'assert pas sur du CSS ni ne mocke une API, il lit le texte
source (source de vérité) via les constantes exportées.
"""
from bouzecode.backend.tools.skill import builtin


def test_fast_testing_prompt_carries_derived_fixture_rule():
    prompt = builtin._FAST_TESTING_PROMPT
    # La section dédiée existe.
    assert "Fixtures DÉRIVÉES du réel" in prompt
    # La règle nomme la vraie valeur d'API (pas une valeur inventée).
    assert "dispatcher:manual" in prompt
    # Le filtre de prod buggé est cité comme exemple avant/après.
    assert "NODES.filter" in prompt
    # La nuance visuel/CSS -> vrai navigateur (happy-dom/jsdom n'applique aucun CSS).
    assert "jsdom" in prompt or "happy-dom" in prompt
