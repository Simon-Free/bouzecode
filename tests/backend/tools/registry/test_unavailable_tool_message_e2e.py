# [desc] A tool the agent cannot call answers with a terminal refusal naming a real substitute. [/desc]
"""Appeler un outil qu'on n'a pas doit COÛTER UN SEUL TOUR.

L'ancien message (« Use /tools enable X ») décrivait une commande REPL que l'agent ne
peut pas émettre et ne proposait aucun substitut : 44 relances mesurées du même appel
refusé. Le nouveau message dit que l'agent ne peut rien activer, qu'insister est inutile,
et nomme des outils pris dans SON registre — jamais une liste écrite en dur.
"""
import pytest

from bouzecode.backend.core.tool_mentions import tool_names_cited
from bouzecode.backend.core.tool_registry import (
    available_tool_names, disable_tool, enable_tool, get_all_tools,
)
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">test</param></tool_use>'


@pytest.fixture
def sans_run_python_test():
    """Un agent dont le profil n'accorde pas RunPythonTest (cas mesuré le plus fréquent)."""
    disable_tool("RunPythonTest")
    yield
    enable_tool("RunPythonTest")


def _refusal(result) -> str:
    refusals = [m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "RunPythonTest"]
    assert refusals, "aucun tool_result pour l'appel refusé"
    return refusals[0]


def test_refused_tool_answers_a_terminal_message_naming_an_available_substitute(sans_run_python_test):
    """L'agent appelle RunPythonTest sans l'avoir : on lui dit qu'il ne peut pas l'activer,
    qu'il ne doit pas réessayer, et on lui donne Bash — qu'il a vraiment."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="RunPythonTest" id="r1">'
        f'<param name="targets">["tests/"]</param></tool_use>',
        "J'utilise Bash à la place.",
    ])

    result = bouzecode(["lance les tests"], mock_llm=mock)
    message = _refusal(result)

    assert "/tools enable" not in message          # ce que l'agent ne peut pas faire
    assert "N'insiste pas" in message              # terminal : ne pas relancer
    assert "`Bash`" in message                     # substitut calculé depuis le registre
    assert "RunPythonTest" not in available_tool_names()


def test_the_refusal_never_names_a_tool_the_agent_does_not_have(sans_run_python_test):
    """Le message de refus est lui-même soumis à la règle qu'il fait respecter."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="RunPythonTest" id="r1"></tool_use>',
        "ok.",
    ])

    message = _refusal(bouzecode(["lance les tests"], mock_llm=mock))

    known = {t.name for t in get_all_tools()}
    cited = tool_names_cited(message, known) - {"RunPythonTest"}
    assert cited, "le refus doit nommer au moins un outil utilisable"
    assert cited <= set(available_tool_names())


def test_an_unknown_tool_name_gets_the_same_terminal_treatment():
    """Un outil qui n'existe pas dans le harnais : même refus terminal, mêmes substituts."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="RunPytest" id="r1"><param name="x">1</param></tool_use>',
        "ok.",
    ])

    result = bouzecode(["lance les tests"], mock_llm=mock)
    message = [m["content"] for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "RunPytest"][0]

    assert "n'existe pas dans ce harnais" in message
    assert "/tools enable" not in message
    assert "Tous les outils dont tu disposes" in message
