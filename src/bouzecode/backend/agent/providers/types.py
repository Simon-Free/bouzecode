# [desc] Defines message/streaming types, tool-name sanitization, and adaptive-thinking model checks. [/desc]
from __future__ import annotations
import re

from .registry import bare_model

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


class ToolCallParsed:
    """Yielded mid-stream when the XML parser finishes a tool_use block."""
    def __init__(self, name: str, inputs: dict, tool_id: str):
        self.name = name
        self.inputs = inputs
        self.tool_id = tool_id


class ToolIdRemap:
    """Yielded after stream ends when tool IDs were remapped by uniquify."""
    def __init__(self, remap: dict[str, str]):
        self.remap = remap


class SystemPayload:
    """Yielded before streaming starts — carries the system_blocks sent to the API,
    plus (in native function-calling mode) the OpenAI-format tools list. `tools` is
    None when the XML tool protocol is used (the Anthropic path, or forced XML)."""
    def __init__(self, system_blocks: list, tools: list | None = None):
        self.system_blocks = system_blocks
        self.tools = tools


class AssistantTurn:
    def __init__(self, text, tool_calls, in_tokens, out_tokens,
                 cache_read_tokens=0, cache_creation_tokens=0, stop_reason=None):
        self.text = text
        self.tool_calls = tool_calls
        self.in_tokens = in_tokens
        self.out_tokens = out_tokens
        self.stop_reason = stop_reason
        self.cache_read_tokens = cache_read_tokens
        self.cache_creation_tokens = cache_creation_tokens
