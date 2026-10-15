# [desc] Tests que le rappel « [RAPPEL — à chaque tour] » n'est plus ajouté au dernier message envoyé au modèle. [/desc]
"""Retiré le 2026-10-05 : collé à la fin du dernier tool_result, ce rappel déclenchait le
content_filter du gateway préprod sur claude-opus-5-5 (6/6 refus avec, 0/14 sans). Le dernier
message part tel que l'historique le porte — demande utilisateur ou résultat d'outil."""
import pytest

from bouzecode.backend.agent.providers.backends.dispatch import stream

REMINDER_HEADER = "[RAPPEL — à chaque tour]"
READ_SCHEMA = {
    "name": "Read",
    "description": "Read a file from disk.",
    "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}},
                     "required": ["file_path"]},
}
USER_REQUEST = [{"role": "user", "content": "Hello"}]
TOOL_RESULT_LAST = [
    {"role": "user", "content": "Lis calc.py"},
    {"role": "assistant", "content": ".", "tool_calls": [
        {"id": "r1", "name": "Read", "input": {"file_path": "calc.py"}}]},
    {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "def add(a, b): ..."},
]


def _last_message_sent(model: str, messages: list) -> str:
    generator = stream(model=model, system="", messages=messages,
                       tool_schemas=[READ_SCHEMA], config={})
    payload = next(generator)
    generator.close()
    # Le bloc <harness_notes> (2026-10-07) suit les tool_results : le dernier message de
    # l'HISTORIQUE est celui qui le précède.
    historique = [m for m in payload.messages if not m.get("_notes_du_harnais")]
    return str(historique[-1].get("content", ""))


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "anthropic/claude-sonnet-4-6"])
@pytest.mark.parametrize("history", [USER_REQUEST, TOOL_RESULT_LAST], ids=["user", "tool_result"])
def test_last_message_sent_has_no_fresh_reminder(monkeypatch, model, history):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-factice")
    last = _last_message_sent(model, history)
    assert REMINDER_HEADER not in last
    assert history[-1]["content"] in last
