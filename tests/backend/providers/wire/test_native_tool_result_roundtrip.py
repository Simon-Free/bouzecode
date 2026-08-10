# [desc] Native wire: a batch of tool calls and their results become paired tool_use/tool_result blocks so the conversation continues. [/desc]
"""Aller-retour natif : ce que l'agent a fait au tour precedent doit repartir sur le
fil sous forme de blocs typés.

L'API refuse un `tool_result` dont le `tool_use_id` n'a pas de `tool_use` correspondant
dans le message assistant qui precede — c'est l'invariant qui casse une conversation en
plein vol, donc c'est lui qu'on epingle ici.
"""
from __future__ import annotations

from bouzecode.backend.agent.providers.backends.anthropic_native import (
    messages_to_anthropic_native,
)


def _blocks(message):
    return message["content"]


def _types(message):
    return [b["type"] for b in message["content"]]


def test_a_tool_batch_and_its_results_come_back_paired():
    """Un tour complet (prose + 2 appels, puis leurs 2 resultats) devient un message
    assistant a blocs typés suivi d'un message user portant les tool_result apparies."""
    conversation = [
        {"role": "user", "content": "liste les fichiers"},
        {"role": "assistant", "content": "Je lance les deux actions.",
         "tool_calls": [
             {"id": "t1", "name": "Glob", "input": {"pattern": "*.py"}},
             {"id": "t2", "name": "Grep", "input": {"pattern": "tool_use"}},
         ]},
        {"role": "tool", "tool_call_id": "t1", "name": "Glob", "content": "a.py\nb.py"},
        {"role": "tool", "tool_call_id": "t2", "name": "Grep", "content": "3 matches"},
        {"role": "user", "content": "merci"},
    ]

    wire = messages_to_anthropic_native(conversation, cache_last=False)

    assistant = wire[1]
    assert assistant["role"] == "assistant"
    assert _types(assistant) == ["text", "tool_use", "tool_use"]
    assert [b["id"] for b in _blocks(assistant)[1:]] == ["t1", "t2"]
    assert _blocks(assistant)[1]["input"] == {"pattern": "*.py"}

    results = wire[2]
    assert results["role"] == "user"
    assert _types(results) == ["tool_result", "tool_result"]
    assert [b["tool_use_id"] for b in _blocks(results)] == ["t1", "t2"]
    assert _blocks(results)[0]["content"] == "a.py\nb.py"

    # Every tool_result is answered by a tool_use declared just above it.
    declared = {b["id"] for b in _blocks(assistant) if b["type"] == "tool_use"}
    assert {b["tool_use_id"] for b in _blocks(results)} == declared
    assert wire[3]["role"] == "user"  # the conversation carries on


def test_an_orphaned_result_gets_its_tool_use_re_declared():
    """La charge minimale peut supprimer le message assistant et ne garder que ses
    resultats. Sans re-declaration l'API rejette le tour : on la synthetise."""
    conversation = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "."},  # tool_calls dropped by the minimal wire
        {"role": "tool", "tool_call_id": "orphan1", "name": "Read", "content": "contenu"},
    ]

    wire = messages_to_anthropic_native(conversation, cache_last=False)

    assistant = wire[1]
    assert "tool_use" in _types(assistant)
    redeclared = [b for b in _blocks(assistant) if b["type"] == "tool_use"]
    assert redeclared[0]["id"] == "orphan1"
    assert redeclared[0]["name"] == "Read"
    assert _blocks(wire[2])[0]["tool_use_id"] == "orphan1"


def test_an_image_result_stays_inside_its_tool_result():
    """Un Read d'image doit rester DANS le tool_result, sinon l'appel reste sans
    reponse et l'API rejette le tour."""
    conversation = [
        {"role": "user", "content": "regarde"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "img1", "name": "Read", "input": {"file_path": "a.png"}}]},
        {"role": "tool", "tool_call_id": "img1", "name": "Read",
         "content": "__BOUZE_IMAGE__:image/png:AAAA"},
    ]

    wire = messages_to_anthropic_native(conversation, cache_last=False)

    result_block = _blocks(wire[2])[0]
    assert result_block["tool_use_id"] == "img1"
    assert result_block["content"][0]["type"] == "image"
    assert result_block["content"][0]["source"]["media_type"] == "image/png"


def test_an_empty_tool_result_is_never_sent_empty():
    """Un resultat vide deviendrait un bloc vide, que l'API refuse."""
    conversation = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "e1", "name": "Bash", "input": {"command": "true"}}]},
        {"role": "tool", "tool_call_id": "e1", "name": "Bash", "content": ""},
    ]

    wire = messages_to_anthropic_native(conversation, cache_last=False)

    assert _blocks(wire[2])[0]["content"].strip()
