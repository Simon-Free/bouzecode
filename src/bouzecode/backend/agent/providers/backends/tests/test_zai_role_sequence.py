"""Z.AI (Zhipu/GLM) rejette un payload sans aucun message `user`.

Reproduction du crash reel : HTTP 400 code 1214 "The messages parameter is
illegal" avec z-ai/glm-5.3 via OpenRouter, sur le tour qui renvoie les
tool_results. Le minimal-wire (build_minimal_payload) garde le message user
HORS du wire (il vit dans le bloc systeme Methodology) et prefixe un stub
`assistant "."` quand le tour n'est que des tool_results -- stub introduit pour
Anthropic, qui refuse un wire commencant par un tool_result.

La fixture ci-dessous est DERIVEE du dump reel
~/.bouzecode/debug_payloads/bb99d62f/turns.jsonl (turn 15) : memes roles, memes
tool_call_id, contenus tronques.
"""
from bouzecode.backend.agent.providers.backends.openrouter_native import (
    messages_to_openai_native,
)


def _crash_wire() -> list[dict]:
    """Le wire exact du crash : stub assistant + 5 tool_results, aucun user."""
    return [
        {"role": "assistant", "content": "."},
        {"role": "tool", "tool_call_id": "t14_m1", "name": "Methodology",
         "content": "methodology append: now 45301 chars"},
        {"role": "tool", "tool_call_id": "t14_s1", "name": "Snippet",
         "content": "snippet saved"},
        {"role": "tool", "tool_call_id": "t14_s2", "name": "Snippet",
         "content": "snippet saved"},
        {"role": "tool", "tool_call_id": "t14_r1", "name": "Read",
         "content": "1\tdef dump_turn_payload(...):\n"},
        {"role": "tool", "tool_call_id": "t14_r2", "name": "Read",
         "content": "1\tdef export_wire(...):\n"},
    ]


def test_tool_results_only_turn_keeps_a_user_message():
    """Repro du 1214 : un tour 'tool_results only' doit quand meme porter un user."""
    out = messages_to_openai_native(_crash_wire(), "SYS")

    roles = [m["role"] for m in out]
    assert "user" in roles, (
        "aucun message role=user sur le wire -> Z.AI repond 400 code 1214 "
        f"(roles envoyes : {roles})"
    )
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user", (
        "le message qui suit le system doit etre un user (Z.AI valide la "
        f"sequence des roles), obtenu : {roles}"
    )


def test_tool_results_are_preserved_and_paired():
    """Non-regression : les 5 tool_results survivent, dans l'ordre, tous apparies."""
    out = messages_to_openai_native(_crash_wire(), "SYS")

    tool_ids = [m["tool_call_id"] for m in out if m["role"] == "tool"]
    assert tool_ids == ["t14_m1", "t14_s1", "t14_s2", "t14_r1", "t14_r2"]

    declared = {
        tc["id"]
        for m in out
        if m["role"] == "assistant"
        for tc in (m.get("tool_calls") or [])
    }
    assert set(tool_ids) <= declared, (
        f"tool_call_id orphelins : {set(tool_ids) - declared}"
    )
    # Chaque tool_result vient APRES l'assistant qui declare son id.
    first_tool = next(i for i, m in enumerate(out) if m["role"] == "tool")
    assert out[first_tool - 1]["role"] == "assistant"


def test_compliant_wire_is_untouched():
    """Un wire qui commence deja par un user ne recoit aucun stub."""
    wire = [
        {"role": "user", "content": "salut"},
        {"role": "assistant", "content": "je regarde",
         "tool_calls": [{"id": "c1", "name": "Bash", "input": {"command": "ls"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "Bash", "content": "a.py"},
    ]
    out = messages_to_openai_native(wire, "SYS")

    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
    assert out[1]["content"] == "salut"
    assert sum(1 for m in out if m["role"] == "user") == 1
