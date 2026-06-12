# [desc] Tests that removing in-wire bounce means sessions close immediately without compliance retry turns. [/desc]
"""Ticket 82fe4b87 : le bounce in-wire (Fallback B) est supprimé — pas de fallback.
Un tour sans tool calls n'a plus de tour de conformité : soit la recovery
out-of-band agit (recover_memory + thinking), soit la session se clôt
immédiatement (close_reason no_tools_text). L'anti-clôture-prématurée est porté
par la recovery et, en headless, par les nudges FinalAnswer — plus par une
fenêtre de contrebande in-wire."""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

from bouzecode.backend.tools.enforcement_hooks import check_enforcement

METH = '<tool_use name="Methodology" id="{i}"><param name="content">etat du travail</param></tool_use>'


def test_tour_thinking_seul_sans_recovery_clot_sans_bounce():
    mock = MockLLM([
        {"thinking": ["analyse longue, mon emission de calls a ete avalee"], "text": ""},
        METH.format(i="m1") + '\n<tool_use name="Bash" id="b1">'
        '<param name="command">echo REEMIS_OK</param></tool_use>',
    ])
    result = bouzecode(["optimise le pipeline"], mock_llm=mock,
                       config_overrides={"recover_memory": False})
    transcript = str(result.messages)
    assert mock.call_count == 1, "pas de tour de conformité : la session se clôt au 1er tour"
    assert "NO tool call from your previous turn was recorded" not in transcript
    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert not bash_results, "aucune ré-émission possible sans recovery ni bounce"


def test_texte_final_sans_methodology_clot_immediatement():
    """A final text without Methodology no longer opens a compliance turn:
    the session closes on the spot (no in-wire smuggling window)."""
    mock = MockLLM([
        "voila ma reponse finale, j'ai oublie la methodology",
        METH.format(i="m3") + '\n<tool_use name="Bash" id="b2">'
        '<param name="command">echo CONTREBANDE</param></tool_use>',
    ])
    result = bouzecode(["question simple"], mock_llm=mock)
    assert mock.call_count == 1, "clôture immédiate sur texte sans tool calls"
    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert not bash_results


def test_message_enforcement_veridique_selon_calls_enregistres():
    sans_calls = check_enforcement([])
    assert "NO tool call from your previous turn was recorded" in sans_calls
    assert "already recorded" not in sans_calls

    avec_calls = check_enforcement([{"id": "x", "name": "Bash", "input": {}}])
    assert "already recorded" in avec_calls
