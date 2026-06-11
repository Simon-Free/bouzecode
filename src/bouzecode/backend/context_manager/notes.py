# [desc] Injects working-memory notes into the last user message. [/desc]
from __future__ import annotations


def inject_notes(messages: list, notes: dict) -> list:
    if not notes:
        return messages
    parts = []
    for name, content in notes.items():
        parts.append(f"## {name}\n{content}")
    notes_block = "[Your working memory notes]\n" + "\n\n".join(parts) + "\n[/Notes]"
    result = list(messages)
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            result[i] = dict(result[i])
            result[i]["content"] = notes_block + "\n\n" + result[i]["content"]
            break
    return result
