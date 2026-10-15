# [desc] Extraction du RAPPORT final (FinalAnswer) d'une session d'agent, sans I/O. [/desc]
"""Le rapport final d'un agent, lu dans les messages de sa session.

Seul reste de l'ancien `_prompts.py` : les prompts du validateur de tickets ont été retirés
avec le validateur (décision D1). Ré-exporté par `tickets` (`tickets.extract_final_answer`)."""
from __future__ import annotations


def extract_final_answer(messages: list[dict]) -> str:
    """Dernier RAPPORT FinalAnswer d'une session : answer du tool_call FinalAnswer,
    sinon contenu d'un tool_result FinalAnswer. Vide si aucun."""
    for message in reversed(messages):
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if call.get("name") == "FinalAnswer":
                    answer = str((call.get("input") or {}).get("answer", "")).strip()
                    if answer:
                        return answer
        elif message.get("role") == "tool" and message.get("name") == "FinalAnswer":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""
