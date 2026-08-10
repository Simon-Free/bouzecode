# [desc] Native Anthropic tool_use over SSE: one block, three interleaved parallel blocks, truncation, scheduling params, and the XML fallback left intact. [/desc]
"""Native `tool_use` on the Anthropic path.

The model answers with typed SSE blocks instead of XML in its prose, and the loop must
end up with exactly the same tool calls it always had. Helpers and the replay seam live
in `anthropic_sse_replay.py`.
"""
from __future__ import annotations

from tests.backend.providers.anthropic_sse_replay import (
    sse, opening, text, tool_open, args, close, closing,
    replay_stream, tool_calls_of, turn_of,
)
from bouzecode.backend.agent.providers import TextChunk

READ_TOOL = [{"name": "Read", "description": "Lit un fichier.",
              "input_schema": {"type": "object",
                               "properties": {"file_path": {"type": "string"}}}}]


def test_one_native_tool_use_block_yields_one_tool_call(monkeypatch):
    """Le modele emet un bloc tool_use natif : la boucle recoit un appel d'outil avec
    le bon nom et les bons arguments, malgre un JSON coupe en morceaux arbitraires."""
    events = sse(*opening(), *text(0, "Je lis le fichier."),
                 tool_open(1, "tooluse_A1", "Read"),
                 args(1, ""), args(1, '{"file'), args(1, '_path": "/tmp/'),
                 args(1, 'a.py"}'), close(1), *closing())

    yielded = replay_stream(monkeypatch, events, READ_TOOL)

    calls = tool_calls_of(yielded)
    assert len(calls) == 1
    assert calls[0].name == "Read"
    assert calls[0].tool_id == "tooluse_A1"
    assert calls[0].inputs == {"file_path": "/tmp/a.py"}
    assert turn_of(yielded).stop_reason == "tool_use"
    # The prose stays prose: a separate content block, never a parse candidate.
    assert "Je lis le fichier." in "".join(
        e.text for e in yielded if isinstance(e, TextChunk))


def test_three_parallel_blocks_interleaved_stay_separate(monkeypatch):
    """Trois appels paralleles dans un seul message : leurs fragments d'arguments
    arrivent MELANGES, distingues seulement par `index`. Chacun doit ressortir avec son
    propre id et ses propres arguments — le cas le plus facile a casser."""
    events = sse(
        *opening(), *text(0, "Trois actions independantes."),
        tool_open(1, "tooluse_M", "Methodology"),
        tool_open(2, "tooluse_G", "Glob"),
        tool_open(3, "tooluse_R", "Grep"),
        # Interleaved exactly as the API streams them.
        args(1, '{"content"'), args(2, '{"pat'), args(3, '{"pattern"'),
        args(2, 'tern": "*.py"}'), args(1, ': "note"}'), args(3, ': "tool_use"}'),
        close(2), close(1), close(3), *closing(),
    )

    calls = tool_calls_of(replay_stream(monkeypatch, events, READ_TOOL))

    # Emitted in closing order, each carrying only its own arguments.
    assert [c.tool_id for c in calls] == ["tooluse_G", "tooluse_M", "tooluse_R"]
    by_id = {c.tool_id: c for c in calls}
    assert by_id["tooluse_M"].inputs == {"content": "note"}
    assert by_id["tooluse_G"].inputs == {"pattern": "*.py"}
    assert by_id["tooluse_R"].inputs == {"pattern": "tool_use"}
    assert len({c.tool_id for c in calls}) == 3


def test_a_truncated_block_does_not_damage_its_siblings(monkeypatch):
    """Flux coupe au milieu d'un bloc : seul CE bloc est signale en erreur, l'appel
    voisin deja ferme reste valide. En XML une troncature contaminait tout le tour."""
    events = sse(*opening(),
                 tool_open(1, "tooluse_OK", "Glob"),
                 args(1, '{"pattern": "*.py"}'), close(1),
                 tool_open(2, "tooluse_CUT", "Read"),
                 args(2, '{"file_path": "/tmp/'),  # never closed
                 *closing())

    calls = tool_calls_of(replay_stream(monkeypatch, events, READ_TOOL))

    assert [c.name for c in calls] == ["Glob", "_ToolArgsParseError"]
    assert calls[0].inputs == {"pattern": "*.py"}
    assert calls[1].inputs["_tool"] == "Read"


def test_scheduling_params_reach_the_dag(monkeypatch):
    """`tool_call_alias` et `depends_on` sont de simples cles du JSON d'arguments en
    natif : le DAG les lit et ordonne bien le dependant en dernier."""
    from bouzecode.backend.agent.dag import _build_dag_levels

    events = sse(*opening(),
                 tool_open(1, "tooluse_W", "Write"),
                 args(1, '{"file_path": "temp_x.py", "content": "x",'),
                 args(1, ' "tool_call_alias": "write_step"}'), close(1),
                 tool_open(2, "tooluse_B", "Bash"),
                 args(2, '{"command": "python temp_x.py",'),
                 args(2, ' "depends_on": ["write_step"]}'), close(2),
                 *closing())

    calls = tool_calls_of(replay_stream(monkeypatch, events, READ_TOOL))
    assert calls[0].inputs["tool_call_alias"] == "write_step"
    assert calls[1].inputs["depends_on"] == ["write_step"]

    levels, _deps = _build_dag_levels(
        [{"id": c.tool_id, "name": c.name, "input": dict(c.inputs)} for c in calls])
    assert [[tc["id"] for tc in level] for level in levels] == [["tooluse_W"], ["tooluse_B"]]


def test_tool_schemas_go_out_in_the_api_tools_param(monkeypatch):
    """En mode natif les schemas partent dans le parametre `tools` de l'API."""
    sent: list = []
    events = sse(*opening(), *text(0, "ok"), *closing(stop_reason="end_turn"))

    replay_stream(monkeypatch, events, READ_TOOL, sent=sent)

    assert sent[0]["tools"] == READ_TOOL


def test_xml_path_is_untouched_when_native_is_off(monkeypatch):
    """Interrupteur OFF : le protocole XML fonctionne exactement comme avant — l'appel
    est parse depuis la prose et aucun `tools` ne part sur le fil."""
    sent: list = []
    xml = ('<tool_use name="Read" id="r1">'
           '<param name="file_path">/tmp/a.py</param></tool_use>')
    events = sse(*opening(), *text(0, f"Je lis.\n{xml}"),
                 *closing(stop_reason="end_turn"))

    calls = tool_calls_of(replay_stream(monkeypatch, events, None, sent=sent))

    assert len(calls) == 1
    assert calls[0].name == "Read"
    assert calls[0].inputs["file_path"] == "/tmp/a.py"
    assert "tools" not in sent[0]
