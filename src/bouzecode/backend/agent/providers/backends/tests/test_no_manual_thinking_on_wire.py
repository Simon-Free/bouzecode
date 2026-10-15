# [desc] Tests qu'aucune consigne de thinking manuel ni réflexion recopiée n'atteint le modèle Anthropic. [/desc]
"""Mesuré le 2026-09-29 sur 3 incidents claude-opus-5 : ces consignes (prompt système, rappel
frais) et la réflexion recopiée en texte déclenchent le classifieur de refus. Retirées :
6/6 réponses correctes au rejeu, contre 0/6."""
import re
from pathlib import Path

import pytest

from bouzecode.backend.agent.providers.conversion import messages_to_anthropic

MAIN_PROMPT = Path(__file__).resolve().parents[6] / "system_prompts" / "01_main_system_prompt.txt"
MANUAL_THINKING_VOCABULARY = re.compile(r"(?i)thinking|\bpens(e|er|ée)\b|réfléchi|raisonn")


def test_main_system_prompt_has_no_manual_thinking_vocabulary():
    assert not MANUAL_THINKING_VOCABULARY.search(MAIN_PROMPT.read_text(encoding="utf-8"))


@pytest.mark.parametrize("model", ["claude-opus-5-5", "deepseek/deepseek-v4.1-flash"])
def test_loud_mode_never_asks_for_reasoning_in_text(model):
    """web_v2 lance TOUS ses agents en `--loud` (runner._agent_cmd). Le mode « Réflexion à Voix
    Haute » (02_think_out_loud.txt) a été supprimé : aucun modèle, natif ou non, ne reçoit plus
    de consigne d'écrire son raisonnement dans des balises `<thinking>`."""
    from bouzecode.backend.core.context import build_system_prompt_parts
    stable, _volatile = build_system_prompt_parts(
        {"model": model, "thinking": True, "thinking_mode": "loud"})
    assert "<thinking>" not in stable
    assert "Réflexion à Voix Haute" not in stable


def test_previous_reasoning_is_not_replayed_as_assistant_text():
    history = [
        {"role": "user", "content": "liste les fichiers"},
        {"role": "assistant", "content": "<thinking>\nje liste E:\\\n</thinking>\n\nJe lance Bash."},
        {"role": "user", "content": "continue"},
    ]
    wire = messages_to_anthropic(history, cache_last=False)
    assert wire[1] == {"role": "assistant", "content": "Je lance Bash."}


def test_reasoning_only_turn_keeps_a_non_empty_placeholder():
    history = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "<thinking>\nrien a dire\n</thinking>"},
        {"role": "user", "content": "continue"},
    ]
    wire = messages_to_anthropic(history, cache_last=False)
    assert wire[1]["content"].strip() and "rien a dire" not in wire[1]["content"]


def test_openai_native_route_does_not_replay_reasoning_as_assistant_text():
    """Route chat/completions (gateway_preprod) : même règle que la route Anthropic."""
    from bouzecode.backend.agent.providers.backends.openrouter_native import messages_to_openai_native
    history = [
        {"role": "user", "content": "liste les fichiers"},
        {"role": "assistant", "content": "<thinking>\nje liste E:\\n</thinking>\n\nJe lance Bash."},
        {"role": "assistant", "content": "<thinking>\nrien a dire\n</thinking>"},
        {"role": "user", "content": "continue"},
    ]
    wire = messages_to_openai_native(history, "system")
    assistant_texts = [m["content"] for m in wire if m["role"] == "assistant"]
    assert assistant_texts[0] == "Je lance Bash."
    assert assistant_texts[1].strip() and "rien a dire" not in assistant_texts[1]
    assert "<thinking>" in history[1]["content"], "l'historique (affichage) n'est pas modifié"


def _overflow_notice(monkeypatch, context_state) -> str:
    """Avis user injecté par la boucle après un dépassement de réflexion (résumé réel par le
    faux streamer, persisté dans la Methodology quand `context_state` est fourni)."""
    import bouzecode.backend.agent.loop as loop_mod
    import bouzecode.backend.agent.thinking_summary as summary_mod
    from bouzecode.backend.agent.providers import AssistantTurn
    from bouzecode.backend.agent.state import AgentState

    def fake_turn(state, config, system, ctx, cancel_check):
        if not any(m.get("_overflow_cut") for m in state.messages):
            ctx.thinking_overflow, ctx.thinking_chars = True, 25000
            ctx.thinking_parts = ["je réfléchis encore " * 1500]
        else:
            ctx.assistant_turn = AssistantTurn(text="J'agis.", tool_calls=[], in_tokens=1,
                                               out_tokens=1, cache_read_tokens=0,
                                               cache_creation_tokens=0)
        return
        yield

    def fake_streamer(**kwargs):
        yield AssistantTurn(text="Conclusion : lire config.py.", tool_calls=[], in_tokens=1,
                            out_tokens=1, cache_read_tokens=0, cache_creation_tokens=0)

    monkeypatch.setattr(loop_mod, "stream_llm_turn", fake_turn)
    monkeypatch.setattr(summary_mod, "get_streamer", lambda: fake_streamer)
    state = AgentState()
    list(loop_mod.run("go", state, {"model": "m", "_context_state": context_state},
                      "system", depth=0))
    cut = next(i for i, m in enumerate(state.messages) if m.get("_overflow_cut"))
    return state.messages[cut + 1]["content"]


@pytest.mark.parametrize("with_methodology", [True, False])
def test_overflow_notice_has_no_reasoning_vocabulary(monkeypatch, with_methodology):
    """Cet avis reste dans TOUS les tours suivants (les messages user ne sont jamais retirés)."""
    import types
    cs = types.SimpleNamespace(notes={}) if with_methodology else None
    notice = _overflow_notice(monkeypatch, cs)
    assert notice.startswith("[SYSTEM] Tour précédent interrompu")
    assert "</thinking>" not in notice
    assert not MANUAL_THINKING_VOCABULARY.search(notice), notice


def test_overflow_summary_call_sends_working_notes_without_reasoning_framing(monkeypatch):
    from bouzecode.backend.agent import thinking_summary
    captured = {}

    def fake_streamer(**kwargs):
        captured.update(kwargs)
        return
        yield

    monkeypatch.setattr(thinking_summary, "get_streamer", lambda: fake_streamer)
    thinking_summary.summarize_overflow("<thinking>\n" + "piste A " * 1000 + "\n</thinking>",
                                        {"model": "m"})
    assert not MANUAL_THINKING_VOCABULARY.search(captured["system"])
    assert "<thinking>" not in captured["messages"][0]["content"]


def test_methodology_recovery_message_omits_turn_reasoning(monkeypatch):
    """Rattrapage Methodology : seed = ce que le tour a FAIT, jamais sa réflexion."""
    import types
    from bouzecode.backend.agent import enforcement_call
    from bouzecode.backend.agent.loop_context import LoopContext

    captured = {}

    def fake_ask(tool_name, system, msg, config, **kwargs):
        captured.update(system=system, msg=msg)
        return [{"id": "m1", "name": "Methodology", "input": {"content": "note"}}]

    ctx = LoopContext()
    ctx.thinking_parts = ["SECRET je pense qu'il faut relire le raisonnement"]
    state = types.SimpleNamespace(messages=[
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "g1", "name": "Glob", "input": {}}]},
        {"role": "tool", "tool_call_id": "g1", "name": "Glob", "content": "src/config.py"},
        {"role": "assistant", "content": "", "tool_calls": []},
    ])
    calls = [{"id": "r1", "name": "Read", "input": {"file_path": "src/config.py"}}]
    monkeypatch.setattr(enforcement_call, "_ask_forced", fake_ask)
    out = enforcement_call.recover_methodology(state, {"model": "m", "methodology_recovery": "llm"},
                                               ctx, calls)
    assert out["name"] == "Methodology"
    assert "SECRET" not in captured["msg"]
    assert "Read" in captured["msg"] and "src/config.py" in captured["msg"]
    assert not MANUAL_THINKING_VOCABULARY.search(captured["msg"]), captured["msg"]
    assert not MANUAL_THINKING_VOCABULARY.search(captured["system"])
