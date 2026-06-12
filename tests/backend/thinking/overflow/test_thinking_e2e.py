# [desc] E2E tests for thinking-out-loud pipeline: parser, loop detector, agent loop integration, and CLI flag
# <tool_use name="FinalAnswer" id="r1"><param name="answer">E2E tests for thinking-out-loud pipeline: parser, loop detector, agent loop integration, and CLI flag</param></tool_use> [/desc]
"""E2E tests for thinking-out-loud pipeline: parser, loop detector, agent loop, CLI flag."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from bouzecode.backend.agent.thinking_parser import ThinkingStreamParser, LoopDetector, strip_thinking_tags
from bouzecode.backend.agent.providers.types import TextChunk, AssistantTurn, StreamStarted
from bouzecode.backend.agent.state import AgentState

# ── helpers ──────────────────────────────────────────────────────────────


def _fake_stream_factory(chunks: list[str], tool_calls=None):
    """Return a generator function that yields StreamStarted + TextChunks + AssistantTurn."""
    def _stream(*, model, system, messages, tool_schemas, config):
        yield StreamStarted()
        full = ""
        for c in chunks:
            full += c
            yield TextChunk(c)
        yield AssistantTurn(
            text=full,
            tool_calls=tool_calls or [],
            in_tokens=10,
            out_tokens=len(full),
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
    return _stream


def _collect_events(gen):
    """Drain a run() generator into a list of events."""
    return list(gen)


def _patch_agent_loop(monkeypatch, fake_stream):
    """Monkeypatch agent.loop dependencies so run() works offline."""
    import bouzecode.backend.agent.loop_turn as _loop_turn
    import bouzecode.backend.agent.loop as _loop
    monkeypatch.setattr(_loop_turn, "stream", fake_stream)
    monkeypatch.setattr(_loop_turn, "get_tool_schemas", lambda: [])
    monkeypatch.setattr(_loop_turn, "_build_messages_for_api", lambda state, config: list(state.messages))
    monkeypatch.setattr(_loop, "_build_messages_for_api", lambda state, config: list(state.messages))
    monkeypatch.setattr(_loop_turn, "dump_turn_payload", lambda *a, **kw: None)
    # Bypass enforcement hooks to prevent extra LLM cycles
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.check_test_enforcement", lambda *a, **kw: None)
    monkeypatch.setattr("bouzecode.backend.tools.enforcement_hooks.get_unsnippeted_reads", lambda *a, **kw: [])


# ══════════════════════════════════════════════════════════════════════════
# 1. Parser unit tests
# ══════════════════════════════════════════════════════════════════════════


class TestThinkingStreamParser:
    def test_simple_thinking_block(self):
        p = ThinkingStreamParser()
        out = p.feed("<thinking>\nhmm let me think\n</thinking>\nvisible text")
        out += p.finalize()
        assert ("thinking", "\nhmm let me think\n") in out
        assert ("text", "\nvisible text") in out

    def test_no_tags(self):
        p = ThinkingStreamParser()
        out = p.feed("just plain text here")
        assert out == [("text", "just plain text here")]

    def test_chunked_across_tag_boundary(self):
        p = ThinkingStreamParser()
        # Tags must be at line start for recognition; close tag needs \n after
        r1 = p.feed("<thinking>insi")
        r2 = p.feed("de\n</thi")
        r3 = p.feed("nking>\nafter")
        all_results = r1 + r2 + r3
        texts = [c for k, c in all_results if k == "text"]
        thinks = [c for k, c in all_results if k == "thinking"]
        assert "".join(texts) == "\nafter"
        assert "".join(thinks) == "inside\n"

    def test_interleaved_blocks(self):
        p = ThinkingStreamParser()
        out = p.feed("<thinking>T1\n</thinking>\nB\n<thinking>T2\n</thinking>\nC")
        out += p.finalize()
        texts = [c for k, c in out if k == "text"]
        thinks = [c for k, c in out if k == "thinking"]
        assert "B" in "".join(texts)
        assert "C" in "".join(texts)
        assert "T1" in "".join(thinks)
        assert "T2" in "".join(thinks)

    def test_accumulates_thinking_text(self):
        p = ThinkingStreamParser()
        p.feed("<thinking>part1\n</thinking>\nmid\n<thinking>part2\n</thinking>\n")
        assert "part1" in p.full_thinking_text
        assert "part2" in p.full_thinking_text

    def test_finalize_flushes_buffer(self):
        p = ThinkingStreamParser()
        r1 = p.feed("<thinking>unclosed")
        r2 = p.finalize()
        all_results = r1 + r2
        thinks = [c for k, c in all_results if k == "thinking"]
        assert "".join(thinks) == "unclosed"

    def test_finalize_flushes_text(self):
        p = ThinkingStreamParser()
        r1 = p.feed("partial<thi")
        r2 = p.finalize()
        all_results = r1 + r2
        texts = [c for k, c in all_results if k == "text"]
        assert "".join(texts) == "partial<thi"


# ══════════════════════════════════════════════════════════════════════════
# 2. Loop detector tests
# ══════════════════════════════════════════════════════════════════════════


class TestLoopDetector:
    def test_short_pattern(self):
        ld = LoopDetector()
        assert ld.feed("ab" * 100) is True

    def test_medium_pattern(self):
        ld = LoopDetector()
        assert ld.feed("hello! " * 80) is True

    def test_no_false_positive(self):
        ld = LoopDetector()
        prose = (
            "The quick brown fox jumps over the lazy dog. "
            "Pack my box with five dozen liquor jugs. "
            "How vexingly quick daft zebras jump! "
        ) * 3
        assert ld.feed(prose) is False

    def test_incremental_feeding(self):
        ld = LoopDetector()
        pattern = "xyz"
        triggered = False
        for _ in range(200):
            if ld.feed(pattern):
                triggered = True
                break
        assert triggered

    def test_short_input_no_trigger(self):
        ld = LoopDetector()
        assert ld.feed("ab" * 5) is False


# ══════════════════════════════════════════════════════════════════════════
# 3. strip_thinking_tags utility
# ══════════════════════════════════════════════════════════════════════════


class TestStripThinkingTags:
    def test_strip_single(self):
        # Tags must be at start of line to be recognized as structural blocks
        assert strip_thinking_tags("before\n<thinking>\nsecret\n</thinking>\nafter") == "before\nafter"

    def test_strip_multiple(self):
        result = strip_thinking_tags("<thinking>\na\n</thinking>\nmid\n<thinking>\nb\n</thinking>\nend")
        assert "mid" in result
        assert "end" in result
        assert "a" not in result
        assert "b" not in result

    def test_no_tags(self):
        assert strip_thinking_tags("plain text") == "plain text"

    def test_multiline(self):
        content = "pre\n<thinking>\nline1\nline2\n</thinking>\npost"
        result = strip_thinking_tags(content)
        assert "pre" in result
        assert "post" in result
        assert "line1" not in result


# ══════════════════════════════════════════════════════════════════════════
# 4. Agent loop e2e tests (mocked LLM)
# ══════════════════════════════════════════════════════════════════════════


class TestAgentLoopThinking:
    def test_thinking_in_text_chunks(self, monkeypatch):
        """TextChunks with thinking tags are yielded by run()."""
        chunks = ["<thinking>let me", " think</thinking>", "The answer is 42."]
        fake = _fake_stream_factory(chunks)
        _patch_agent_loop(monkeypatch, fake)

        from bouzecode.backend.agent.loop import run
        state = AgentState()
        config = {"model": "test-model", "_session_id": "test", "_all_plans": ["test"], "_context_state": state.context_state}
        events = _collect_events(run("hello", state, config, "system"))

        text_events = [e for e in events if isinstance(e, TextChunk)]
        assert len(text_events) >= 3
        assert text_events[0].text == "<thinking>let me"

    def test_thinking_stored_in_messages(self, monkeypatch):
        """The raw text (with thinking tags) is stored in state.messages."""
        chunks = ["<thinking>deep thought</thinking>visible answer"]
        fake = _fake_stream_factory(chunks)
        _patch_agent_loop(monkeypatch, fake)

        from bouzecode.backend.agent.loop import run
        state = AgentState()
        config = {"model": "test-model"}
        _collect_events(run("q", state, config, "sys"))

        asst_msgs = [m for m in state.messages if m["role"] == "assistant"]
        assert len(asst_msgs) == 1
        assert "<thinking>" in asst_msgs[0]["content"]
        assert "visible answer" in asst_msgs[0]["content"]

    def test_thinking_stripped_from_api_payload(self, monkeypatch):
        """build_messages_for_api strips thinking tags from messages."""
        from bouzecode.backend.agent.minimal_payload import build_messages_for_api

        state = AgentState()
        state.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "<thinking>secret</thinking>answer", "tool_calls": []},
            {"role": "user", "content": "follow up"},
        ]
        config = {"model": "test-model", "_context_state": state.context_state}

        api_msgs = build_messages_for_api(state, config)
        for msg in api_msgs:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    assert "<thinking>" not in content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            assert "<thinking>" not in block["text"]

    def test_full_roundtrip(self, monkeypatch):
        """End-to-end: run() stores raw thinking; build_messages_for_api keeps
        no trace of <thinking> in any wire message (dropped prior assts take it
        with them, and live-batch assts have it stripped by _strip_thinking)."""
        chunks = ["<thinking>reasoning here</thinking>final answer"]
        fake = _fake_stream_factory(chunks)
        _patch_agent_loop(monkeypatch, fake)

        from bouzecode.backend.agent.loop import run
        state = AgentState()
        config = {"model": "test-model", "_context_state": state.context_state}
        _collect_events(run("test", state, config, "sys"))

        # Raw stored
        asst = [m for m in state.messages if m["role"] == "assistant"][0]
        assert "<thinking>" in asst["content"]

        # No thinking anywhere in the API payload, regardless of which messages survived.
        from bouzecode.backend.agent.minimal_payload import build_messages_for_api
        api_msgs = build_messages_for_api(state, config)
        for msg in api_msgs:
            content = msg.get("content", "")
            if isinstance(content, str):
                assert "<thinking>" not in content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        assert "<thinking>" not in block["text"]

    def test_multi_turn_thinking(self, monkeypatch):
        """Multiple turns with thinking: all stored raw, all stripped for API."""
        import bouzecode.backend.agent.loop as _loop

        turn = [0]
        responses = [
            ["<thinking>turn1 think</thinking>turn1 answer"],
            ["<thinking>turn2 think</thinking>turn2 answer"],
        ]

        def _multi_stream(*, model, system, messages, tool_schemas, config):
            idx = min(turn[0], len(responses) - 1)
            chunks = responses[idx]
            turn[0] += 1
            full = "".join(chunks)
            yield StreamStarted()
            for c in chunks:
                yield TextChunk(c)
            yield AssistantTurn(text=full, tool_calls=[], in_tokens=10,
                                out_tokens=len(full))

        _patch_agent_loop(monkeypatch, _multi_stream)

        from bouzecode.backend.agent.loop import run
        state = AgentState()
        config = {"model": "test-model", "_context_state": state.context_state}

        _collect_events(run("first", state, config, "sys"))
        _collect_events(run("second", state, config, "sys"))

        asst_msgs = [m for m in state.messages if m["role"] == "assistant"]
        assert len(asst_msgs) == 2
        for m in asst_msgs:
            assert "<thinking>" in m["content"]

        from bouzecode.backend.agent.minimal_payload import build_messages_for_api
        api_msgs = build_messages_for_api(state, config)
        for m in api_msgs:
            if m.get("role") == "assistant":
                content = m.get("content", "")
                if isinstance(content, str):
                    assert "<thinking>" not in content

    def test_plain_text_no_stripping(self, monkeypatch):
        """Live-batch: assistant is dropped from wire, tool_results kept intact."""
        from bouzecode.backend.agent.minimal_payload import build_messages_for_api

        state = AgentState()
        state.messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "just a normal answer",
             "tool_calls": [{"id": "b1", "name": "Bash", "input": {}}]},
            {"role": "tool", "tool_call_id": "b1", "name": "Bash", "content": "ok"},
        ]
        config = {"model": "test-model", "_context_state": state.context_state}

        api_msgs = build_messages_for_api(state, config)
        # The assistant's prose is dropped (methodology-centric). A minimal
        # assistant stub may remain only to satisfy the API's leading-role
        # requirement, so assert the *prose* is gone rather than zero assistants.
        assert not any(
            "just a normal answer" in str(m.get("content", "")) for m in api_msgs
        )
        # Tool result is present on wire
        tool_msgs = [m for m in api_msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "ok" in tool_msgs[0]["content"]

    def test_thinking_list_blocks_stripped(self, monkeypatch):
        """Thinking tags are stripped from messages — no thinking leaks on wire."""
        from bouzecode.backend.agent.minimal_payload import build_messages_for_api

        state = AgentState()
        state.messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "<thinking>secret</thinking>visible"},
            ], "tool_calls": [{"id": "b1", "name": "Bash", "input": {}}]},
            {"role": "tool", "tool_call_id": "b1", "name": "Bash", "content": "ok"},
        ]
        config = {"model": "test-model", "_context_state": state.context_state}

        api_msgs = build_messages_for_api(state, config)
        # No thinking should leak into any message on wire
        for msg in api_msgs:
            content = msg.get("content", "")
            if isinstance(content, str):
                assert "<thinking>" not in content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        assert "<thinking>" not in block.get("text", "")


# ══════════════════════════════════════════════════════════════════════════
# 5. CLI flag tests
# ══════════════════════════════════════════════════════════════════════════


class TestCLIFlags:
    def _patch_cli(self, monkeypatch, argv, capture_dict=None):
        """Patch sys.argv and mock config/repl imports used inside bouzecode.main()."""
        import bouzecode.backend.core.config as config_mod
        import bouzecode.ui.repl as repl_mod

        monkeypatch.setattr(sys, "argv", ["bouzecode"] + argv)
        monkeypatch.setattr(config_mod, "load_config", lambda: {"model": "test"})
        monkeypatch.setattr(config_mod, "has_api_key", lambda m: True)

        def _fake_repl(config, initial_prompt=None):
            if capture_dict is not None:
                capture_dict.update(config)

        monkeypatch.setattr(repl_mod, "repl", _fake_repl)

    def test_loud_flag(self, monkeypatch):
        """--loud is accepted without error."""
        self._patch_cli(monkeypatch, ["--loud", "--accept-all"])
        import bouzecode as _cli
        _cli.main()

    def test_thinking_flag_compat(self, monkeypatch):
        """--thinking still works as before."""
        self._patch_cli(monkeypatch, ["--thinking", "--accept-all"])
        import bouzecode as _cli
        _cli.main()

    def test_loud_flag_sets_thinking(self, monkeypatch):
        """--loud sets config['thinking'] = True and thinking_mode = 'loud'."""
        captured = {}
        self._patch_cli(monkeypatch, ["--loud", "--accept-all"], captured)
        import bouzecode as _cli
        _cli.main()
        assert captured.get("thinking") is True
        assert captured.get("thinking_mode") == "loud"

    def test_thinking_flag_sets_extended(self, monkeypatch):
        """--thinking sets thinking_mode = 'extended'."""
        captured = {}
        self._patch_cli(monkeypatch, ["--thinking", "--accept-all"], captured)
        import bouzecode as _cli
        _cli.main()
        assert captured.get("thinking") is True
        assert captured.get("thinking_mode") == "extended"
