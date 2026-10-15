# [desc] Strips tool-call XML from assistant text, keeping <thinking> blocks. [/desc]
"""Retire le XML d'appels d'outils d'un texte assistant (utilisé par le replay CLI)."""
from __future__ import annotations

import re

# Permissive: matches <tool_use ...any attrs...>...</tool_use>
_TOOL_USE_RE = re.compile(r'<tool_use\b[^>]*>.*?</tool_use>', re.DOTALL)

# Matches "[Response from tool_use name="..." id="..."]" followed by content
# up to the next [Response from ...] header, next <tool_use, or end of string
_RESPONSE_BLOCK_RE = re.compile(
    r'\[Response from tool_use\s+name="[^"]*"\s+id="[^"]*"\]\n?'
    r'.*?'
    r'(?=\[Response from tool_use\s|<tool_use\b|\Z)',
    re.DOTALL,
)


_THINKING_BLOCK_RE = re.compile(
    r'^<thinking>[ \t]*\n.*?^</thinking>[ \t]*$|<thinking>[^\n]*?</thinking>',
    re.DOTALL | re.MULTILINE,
)


def strip_tool_xml(text: str) -> str:
    """Remove <tool_use> XML blocks and [Response from ...] blocks from assistant content."""
    # Protect thinking blocks from being stripped
    placeholders: list[str] = []

    def _save_thinking(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00THINKING_{len(placeholders) - 1}\x00"

    text_protected = _THINKING_BLOCK_RE.sub(_save_thinking, text)
    cleaned = _TOOL_USE_RE.sub("", text_protected)
    cleaned = _RESPONSE_BLOCK_RE.sub("", cleaned)
    # Restore thinking blocks
    for i, block in enumerate(placeholders):
        cleaned = cleaned.replace(f"\x00THINKING_{i}\x00", block)
    cleaned = cleaned.strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)

