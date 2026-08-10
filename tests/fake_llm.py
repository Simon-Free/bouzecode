# [desc] Mock LLM for e2e tests — streams raw text with XML tool_use blocks through XmlToolStreamParser [/desc]
"""Mock LLM for e2e tests — responses are raw text strings containing XML tool_use blocks.

The MockLLM uses XmlToolStreamParser to parse tool calls from the text,
exactly like the real Anthropic stream backend. This means tests fail if
the XML format is wrong — providing realistic validation.
"""
from __future__ import annotations

from bouzecode.backend.agent.providers.types import AssistantTurn, TextChunk, ThinkingChunk, StreamStarted, ToolCallParsed
from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser


class MockLLM:
    """Pre-configured LLM responses for e2e tests.

    Each response is a raw text string that may contain <tool_use> XML blocks.
    The stream() method parses XML using XmlToolStreamParser and yields the
    same event types as the real provider backend.

    Example:
        mock = MockLLM([
            '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>',
            "The command said hi.",
        ])
    """

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_index = 0
        self.recorded_calls: list[dict] = []
        # Answer served to SIDE calls — the nested completions the engine makes on
        # its own behalf (thinking-overflow summary, close validator…), marked by
        # `config["_depth"]`. They are not turns of the conversation: served from
        # the main script they would silently shift every following reply by one,
        # and the summary the test asserts on would be the next turn's text.
        # Left at None, a side call falls through to the script as before.
        self.side_call_response: str | None = None
        self.side_calls: list[dict] = []

    def stream(self, model, system, messages, tool_schemas, config):
        if self.side_call_response is not None and (config or {}).get("_depth"):
            self.side_calls.append({"model": model, "system": system,
                                    "messages": list(messages)})
            yield from self._emit(self.side_call_response, [], "end_turn")
            return

        assert self.call_index < len(self.responses), (
            f"MockLLM: stream() called {self.call_index + 1} times, "
            f"only {len(self.responses)} responses configured"
        )
        entry = self.responses[self.call_index]
        thinking_parts: list[str] = []
        if isinstance(entry, dict):
            # {"thinking": list[str], "text": str, "stop_reason": str} — lets a
            # response stream real ThinkingChunk events before its visible text,
            # mirroring Anthropic's separate thinking/text content blocks.
            raw_text = entry.get("text", "")
            stop_reason = entry.get("stop_reason", "end_turn")
            thinking_parts = entry.get("thinking") or []
        elif isinstance(entry, tuple):
            raw_text, stop_reason = entry
        else:
            raw_text = entry
            stop_reason = "end_turn"
        self.recorded_calls.append({
            "model": model,
            "system": system,
            "messages": list(messages),
            "tool_schemas": tool_schemas,
            "call_index": self.call_index,
        })
        self.call_index += 1

        yield from self._emit(raw_text, thinking_parts, stop_reason)

    def _emit(self, raw_text, thinking_parts, stop_reason):
        """Stream one canned answer as the real backend would."""
        yield StreamStarted()

        for _thought in thinking_parts:
            yield ThinkingChunk(_thought)

        parser = XmlToolStreamParser()
        tool_calls = []

        for item in parser.feed(raw_text):
            if isinstance(item, str):
                yield TextChunk(item)
            else:
                yield ToolCallParsed(item["name"], item["input"], item["id"])
                tool_calls.append(item)

        finalized = parser.finalize()
        for tc in finalized:
            yield ToolCallParsed(tc["name"], tc["input"], tc["id"])
            tool_calls.append(tc)

        yield AssistantTurn(
            text=raw_text,
            tool_calls=tool_calls,
            in_tokens=0,
            out_tokens=0,
            stop_reason=stop_reason,
        )

    @property
    def call_count(self) -> int:
        return self.call_index

    def get_messages(self, call_index: int) -> list[dict]:
        assert call_index < len(self.recorded_calls), (
            f"No recorded call at index {call_index}"
        )
        return self.recorded_calls[call_index]["messages"]
