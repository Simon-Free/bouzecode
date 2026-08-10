# [desc] In plan mode the write tools leave the schema entirely, and come back on exit. [/desc]
"""Le plan mode était le dernier endroit où un outil restait OFFERT tout en étant refusé.

L'agent voyait Write/Edit dans ses outils, les appelait, se faisait bloquer, et payait
un tour. Désormais ils quittent le schéma pendant le plan mode (le prompt RÉTRÉCIT :
deux schémas de moins dans le préfixe caché) et reviennent à la sortie. Le plan lui-même
s'écrit avec WritePlan, framework always-on, donc jamais retiré.
"""
import pytest

from bouzecode.backend.core.tool_registry import (
    disable_tool, enable_tool, get_tool_schemas, is_enabled,
)
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">plan</param></tool_use>'


@pytest.fixture
def plan_mode_tools_offered():
    """Un agent qui a le droit d'entrer et de sortir du plan mode lui-même."""
    enable_tool("EnterPlanMode")
    enable_tool("ExitPlanMode")
    yield
    disable_tool("EnterPlanMode")
    disable_tool("ExitPlanMode")
    for name in ("Write", "Edit", "NotebookEdit"):
        enable_tool(name)
    disable_tool("NotebookEdit")


def _offered() -> set:
    return {schema["name"] for schema in get_tool_schemas()}


def test_entering_plan_mode_removes_write_and_edit_from_the_offered_tools(plan_mode_tools_offered):
    """Après EnterPlanMode, l'agent ne se voit plus proposer Write/Edit — mais garde WritePlan."""
    assert {"Write", "Edit"} <= _offered()

    mock = MockLLM([
        f'{METH}\n<tool_use name="EnterPlanMode" id="p1">'
        f'<param name="task_description">refonte du parseur</param></tool_use>',
        "Je rédige le plan.",
    ])
    bouzecode(["prépare un plan"], mock_llm=mock)

    offered = _offered()
    assert "Write" not in offered and "Edit" not in offered
    assert "WritePlan" in offered
    assert "Read" in offered and "Grep" in offered      # l'analyse reste possible


def test_leaving_plan_mode_gives_the_write_tools_back(plan_mode_tools_offered):
    """Sortie de plan mode : l'agent retrouve exactement ce qu'il avait avant."""
    avant = _offered()

    mock = MockLLM([
        f'{METH}\n<tool_use name="EnterPlanMode" id="p1"></tool_use>',
        f'{METH}\n<tool_use name="WritePlan" id="w1">'
        f'<param name="content">## Plan\n- etape 1</param></tool_use>',
        f'{METH}\n<tool_use name="ExitPlanMode" id="x1"></tool_use>',
        "Plan prêt.",
    ])
    bouzecode(["prépare un plan"], mock_llm=mock)

    assert _offered() == avant


def test_a_tool_the_profile_never_had_is_not_handed_out_on_exit(plan_mode_tools_offered):
    """Le retour d'échange rend ce qui a été retiré, pas plus : NotebookEdit, désactivé
    par la whitelist, ne doit pas être « restauré » par la sortie du plan mode."""
    disable_tool("NotebookEdit")
    assert not is_enabled("NotebookEdit")

    mock = MockLLM([
        f'{METH}\n<tool_use name="EnterPlanMode" id="p1"></tool_use>',
        f'{METH}\n<tool_use name="ExitPlanMode" id="x1"></tool_use>',
        "fini.",
    ])
    bouzecode(["prépare un plan"], mock_llm=mock)

    assert not is_enabled("NotebookEdit")
