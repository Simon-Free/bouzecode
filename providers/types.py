# [desc] Defines message/streaming types, tool-name sanitization, and adaptive-thinking model checks. [/desc]
from __future__ import annotations
import re

from providers.registry import bare_model

_VALID_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_INVALID_TOOL_NAME_PLACEHOLDER = "_InvalidToolName"


def sanitize_tool_name(raw_name: str) -> tuple[str, str | None]:
    if raw_name and _VALID_TOOL_NAME_RE.match(raw_name):
        return raw_name, None
    return _INVALID_TOOL_NAME_PLACEHOLDER, raw_name


_ADAPTIVE_THINKING_MODELS = {
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-mythos-preview",
}


def _supports_adaptive_thinking(model: str) -> bool:
    return bare_model(model) in _ADAPTIVE_THINKING_MODELS


class StreamStarted:
    pass


class TextChunk:
    def __init__(self, text): self.text = text


class ThinkingChunk:
    def __init__(self, text): self.text = text


class AssistantTurn:
    def __init__(self, text, tool_calls, in_tokens, out_tokens,
                 cache_read_tokens=0, cache_creation_tokens=0):
        self.text = text
        self.tool_calls = tool_calls
        self.in_tokens = in_tokens
        self.out_tokens = out_tokens
        self.cache_read_tokens = cache_read_tokens
        self.cache_creation_tokens = cache_creation_tokens
