"""Regression: a model that writes the HARNESS's own turn must not be believed.

Focus conversation 6e67be34 (2026-08-18): the model emitted its <tool_use> blocks
and, in the SAME completion, carried on writing what it imagined the results were
-- opening with `tool<tool_use_result id="r1">` and a made-up DEMODB schema. It then
queried tables that do not exist, invented the rows, and closed with final_answer.
Every figure delivered to the user was fabricated.

The existing XML parser already swallows `<tool_result` (the tag the harness itself
serialises). It missed this one because the model wrote `<tool_use_result` -- a
near-miss tag -- and swallowing is cosmetic anyway: it hides the text without
stopping the model from reasoning on its fiction, and without keeping the fiction
out of the assistant message persisted to history.

The rule here is prompt_echo's, one step further: text the harness authors is never
the model's own content. prompt_echo DROPS such a line; this CUTS the turn at it,
so the tool calls already parsed still run and the loop delivers their real results.
"""

from bouzecode.backend.agent.providers.backends.role_leak import cut_at_role_leak
from bouzecode.backend.agent.providers.types import (
    AssistantTurn, TextChunk, ThinkingChunk, ToolCallParsed,
)

# Verbatim from the conversation, tool entry 5 (an `intermediate_text`, i.e. tokens
# the model produced -- not a result it received).
LEAK = (
    'tool<tool_use_result id="r1">\n'
    "==== A SNIPPETER id: tool_id=r1 ====\n"
    "[Instructions DEMODB chargées]\n"
    "- F_TRAIN_JOUR : agrégats par train et par jour de circulation.\n"
    "</tool_use_result>\n"
)
BEFORE = "Je charge le schéma DEMODB et les instructions en parallèle.\n"


def run(events, native_tools=False):
    return list(cut_at_role_leak(iter(events), native_tools=native_tools))


def texts(events):
    return "".join(e.text for e in events if isinstance(e, TextChunk))


def test_text_before_the_leak_survives():
    kept = run([TextChunk(BEFORE + LEAK)])
    assert texts(kept) == BEFORE


def test_the_fabricated_result_never_reaches_the_consumer():
    kept = texts(run([TextChunk(BEFORE + LEAK)]))
    assert "F_TRAIN_JOUR" not in kept
    assert "tool_use_result" not in kept


def test_a_marker_split_across_chunks_is_still_caught():
    kept = run([TextChunk(BEFORE + "tool<tool_use"), TextChunk('_result id="r1">\nF_TRAIN_JOUR')])
    assert texts(kept) == BEFORE


def test_everything_the_model_writes_after_the_leak_is_dropped():
    kept = run([
        TextChunk(BEFORE), TextChunk(LEAK),
        ThinkingChunk("Données propres, 4 axes."),
        TextChunk("| SUD EST | 1587200 | 1523400 |"),
    ])
    assert texts(kept) == BEFORE
    assert not [e for e in kept if isinstance(e, ThinkingChunk)]


def test_the_tool_calls_emitted_before_the_leak_still_run():
    turn = AssistantTurn(BEFORE + LEAK, [{"name": "get_demodb_schema", "id": "r2"}], 0, 0)
    kept = run([TextChunk(BEFORE), ToolCallParsed("get_demodb_schema", {}, "r2"),
                TextChunk(LEAK), turn])
    assert [e.tool_id for e in kept if isinstance(e, ToolCallParsed)] == ["r2"]
    assert [tc["name"] for tc in kept[-1].tool_calls] == ["get_demodb_schema"]


def test_the_tool_calls_invented_after_the_leak_are_dropped():
    """execute_sql, execute_python and final_answer rode on the fabricated results."""
    turn = AssistantTurn(
        BEFORE + LEAK,
        [{"name": "get_demodb_schema", "id": "r2"}, {"name": "execute_sql", "id": "q1"},
         {"name": "final_answer", "id": "f1"}],
        0, 0,
    )
    kept = run([TextChunk(BEFORE), ToolCallParsed("get_demodb_schema", {}, "r2"),
                TextChunk(LEAK), ToolCallParsed("execute_sql", {}, "q1"), turn])
    assert [tc["name"] for tc in kept[-1].tool_calls] == ["get_demodb_schema"]


def test_the_assistant_text_persisted_to_history_is_truncated():
    """Otherwise the next iteration reads the fiction as its own established fact."""
    turn = AssistantTurn(BEFORE + LEAK, [], 0, 0)
    kept = run([TextChunk(BEFORE), TextChunk(LEAK), turn])
    assert kept[-1].text == BEFORE


def test_native_tool_calls_are_never_dropped():
    """Native calls arrive out of band: their position in the text means nothing."""
    turn = AssistantTurn(BEFORE + LEAK, [{"name": "execute_sql", "id": "q1"}], 0, 0)
    kept = run([TextChunk(BEFORE), TextChunk(LEAK), turn], native_tools=True)
    assert [tc["name"] for tc in kept[-1].tool_calls] == ["execute_sql"]
    assert kept[-1].text == BEFORE


def test_an_ordinary_answer_passes_through_untouched():
    answer = "La capacité réelle est inférieure à la prévision J-30 de 3 %.\nVoir le graphique.\n"
    kept = run([TextChunk(answer), AssistantTurn(answer, [], 0, 0)])
    assert texts(kept) == answer
    assert kept[-1].text == answer


def test_the_harness_own_reminder_quoted_back_is_a_leak():
    """`user[RAPPEL] Tu n'as pas encore appelé final_answer` -- conversation 9c13b909."""
    kept = run([TextChunk("Je continue.\nuser[RAPPEL] Tu n'as pas encore appelé final_answer.")])
    assert texts(kept) == "Je continue.\n"
