# [desc] Drops from the model's visible text the prompt lines bouzecode itself injected [/desc]
"""Garde-fou contre la régurgitation du prompt par le modèle."""

from ..types import TextChunk

# Une ligne plus courte que ça pourrait apparaître par hasard dans une réponse.
# Au-delà, l'égalité EXACTE avec une ligne que nous avons écrite suffit : c'est
# une certitude, pas une heuristique.
_MIN_LINE = 24


def echoed_lines(texts, min_line: int = _MIN_LINE) -> set[str]:
    """The injected lines long enough to be unmistakable if a model repeats them."""
    lines: set[str] = set()
    for text in texts:
        for line in (text or "").splitlines():
            stripped = line.strip()
            if len(stripped) >= min_line:
                lines.add(stripped)
    return lines


def _split_settled(buffer: str, lines: set[str]) -> tuple[str, str]:
    """Return (text to emit, text still held) for the complete lines of *buffer*.

    The trailing fragment is held only while it could still grow into an injected
    line, so ordinary text keeps streaming token by token.
    """
    *complete, partial = buffer.split("\n")
    kept = [line for line in complete if line.strip() not in lines]
    emitted = "".join(line + "\n" for line in kept)
    if partial and any(line.startswith(partial.lstrip()) for line in lines):
        return emitted, partial
    return emitted + partial, ""


def drop_prompt_echo(events, texts, min_line: int = _MIN_LINE):
    """Strip from the streamed text any line bouzecode wrote into the prompt.

    Some models open a turn by reciting the reminder appended to the last user
    message. Measured on Focus conversation ba0d2431: 19 of its 20 turns
    reproduced the reminder's 1271 trailing characters byte for byte (the 20th
    swapped a single word, which is what proves a model wrote it and not a code
    path). The recitation starts at the `<thinking>` the reminder itself cites,
    so every `<thinking>` parser — Focus's bridge and bouzecode's own — opened a
    block on it and displayed the turn protocol as the model's reasoning.

    Renaming that tag would only move the problem: every prompt documenting the
    protocol has to spell the tags out. What holds whatever the wording is: a
    long line we injected ourselves is never the model's own content.
    """
    lines = echoed_lines(texts, min_line)
    if not lines:
        yield from events
        return
    held = ""
    for event in events:
        if not isinstance(event, TextChunk):
            if held:
                yield TextChunk(held)
                held = ""
            yield event
            continue
        emitted, held = _split_settled(held + event.text, lines)
        if emitted:
            yield TextChunk(emitted)
    if held:
        yield TextChunk(held)
