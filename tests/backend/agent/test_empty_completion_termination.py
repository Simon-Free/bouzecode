"""Une complétion VIDE du modèle ne doit JAMAIS faire boucler un agent en silence.

Bug mesuré le 2026-08-26 : trois agents ont brûlé 184K-266K tokens en boucle stérile à
~0,2 s le tour, sans crash. Mécanique : réponse vide -> nudge user derrière un assistant
sans tool_calls -> `minimal_payload` ne voyait plus de batch « live » et n'envoyait plus
qu'UN message (contexte rasé, keep=0) -> requête dégénérée -> nouvelle réponse vide.

Injection de la fausse réponse LLM par le point d'extension maison (`MockLLM` +
`e2e_harness.bouzecode`) : aucun `mock.patch`. Une entrée `""` de MockLLM produit
exactement `AssistantTurn(text="", tool_calls=[], stop_reason="end_turn")`, soit la
complétion vide du bug.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_harness import bouzecode  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

# Un premier tour PRODUCTIF : Methodology (exigée par l'enforcement) + un tool réel, pour
# qu'un batch de tool_results existe sur le fil — c'est lui que le bug rasait.
PRODUCTIVE_TURN = (
    "Je commence.\n"
    '<tool_use name="Methodology" id="m1"><param name="content">plan initial</param></tool_use>\n'
    '<tool_use name="Bash" id="b1"><param name="command">echo hello</param></tool_use>'
)


def test_empty_completion_terminates_run_without_razing_context():
    # Beaucoup plus de réponses vides que le budget : si la boucle n'était pas bornée,
    # MockLLM lèverait son AssertionError une fois la liste épuisée.
    empties = [""] * 40
    mock = MockLLM([PRODUCTIVE_TURN, *empties])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides={"close_requires_final_answer": True})

    # (b) le run se termine avec la raison explicite dédiée
    assert result.state.close_reason == "empty_completion", (
        f"close_reason={result.state.close_reason!r}, attendu 'empty_completion'"
    )
    assert result.state.close_detail, "close_detail humain manquant"
    assert "vide" in result.state.close_detail

    # (c) le coupe-circuit borne le nombre de tours : 1 productif + un petit budget de
    # relances, très loin des 12+ tours stériles de l'ancien chemin.
    assert mock.call_count <= 6, f"{mock.call_count} appels LLM — boucle non bornée"
    assert mock.call_count < len(mock.responses)

    # (a) aucun rasage du contexte : le dernier payload envoyé porte encore le batch de
    # tool_results du tour productif (anti keep=0 / api_input_tokens sous le system).
    last_payload = mock.get_messages(mock.call_count - 1)
    assert any(m.get("role") == "tool" for m in last_payload), (
        f"contexte rasé — payload envoyé : {last_payload!r}"
    )


def test_empty_completion_reason_is_declared_in_close_reasons_table():
    from bouzecode.web_v2.close_reasons import (
        CLOSURES, CONTROLLED_CLOSE_REASONS,
        DELIVERY_CLOSE_REASONS,
    )
    assert "empty_completion" in CLOSURES  # sinon UNKNOWN=_CRASH -> classé mort en vol
    assert "empty_completion" in CONTROLLED_CLOSE_REASONS  # la boucle a décidé de clore
    assert "empty_completion" not in DELIVERY_CLOSE_REASONS  # rien n'est livré


def test_text_without_tools_is_not_treated_as_empty_completion():
    """Non-régression du nominal : un tour AVEC texte et sans tool call garde son
    traitement habituel (nudge puis clôture normale), jamais 'empty_completion'."""
    mock = MockLLM([
        PRODUCTIVE_TURN,
        *["Voilà, le travail est terminé." for _ in range(15)],
    ])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True)

    assert result.state.close_reason != "empty_completion", (
        "un tour de texte sans tool call a été confondu avec une complétion vide"
    )
