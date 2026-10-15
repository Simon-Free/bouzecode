# [desc] Tests for ThinkingStreamParser covering streaming, chunked input, and edge cases [/desc]
"""Tests for ThinkingStreamParser with line-start-only tag recognition."""
import sys
sys.path.insert(0, r"C:\Users\user01\PycharmProjects\demo\bouzecode")

from bouzecode.backend.agent.thinking_parser import ThinkingStreamParser, LoopDetector, strip_thinking_tags


class TestThinkingStreamParser:
    def test_no_thinking_tags(self):
        p = ThinkingStreamParser()
        events = p.feed("Hello world")
        events += p.finalize()
        texts = "".join(t for k, t in events if k == "text")
        assert texts == "Hello world"
        assert not any(k == "thinking" for k, _ in events)

    def test_basic_thinking_block(self):
        p = ThinkingStreamParser()
        events = p.feed("<thinking>\nreasoning\n</thinking>\nanswer")
        events += p.finalize()
        thinking = "".join(t for k, t in events if k == "thinking")
        text = "".join(t for k, t in events if k == "text")
        assert "reasoning" in thinking
        assert "answer" in text

    def test_multiple_blocks(self):
        p = ThinkingStreamParser()
        events = p.feed("<thinking>\nA\n</thinking>\nX\n<thinking>\nB\n</thinking>\nY")
        events += p.finalize()
        thinking = "".join(t for k, t in events if k == "thinking")
        text = "".join(t for k, t in events if k == "text")
        assert "A" in thinking and "B" in thinking
        assert "X" in text and "Y" in text

    def test_partial_open_tag_across_chunks(self):
        p = ThinkingStreamParser()
        all_events = []
        all_events += p.feed("before\n<thi")
        all_events += p.feed("nking>\ninside\n</thinking>\nafter")
        all_events += p.finalize()
        thinking = "".join(t for k, t in all_events if k == "thinking")
        text = "".join(t for k, t in all_events if k == "text")
        assert "inside" in thinking
        assert "before" in text and "after" in text

    def test_partial_close_tag_across_chunks(self):
        p = ThinkingStreamParser()
        all_events = []
        all_events += p.feed("<thinking>\ninside\n</thin")
        all_events += p.feed("king>\noutside")
        all_events += p.finalize()
        thinking = "".join(t for k, t in all_events if k == "thinking")
        text = "".join(t for k, t in all_events if k == "text")
        assert "inside" in thinking
        assert "outside" in text

    def test_unclosed_tag_flushed_on_finalize(self):
        p = ThinkingStreamParser()
        events = p.feed("<thinking>\nunclosed")
        events += p.finalize()
        thinking = "".join(t for k, t in events if k == "thinking")
        assert "unclosed" in thinking

    def test_text_before_thinking(self):
        p = ThinkingStreamParser()
        events = p.feed("before\n<thinking>\nduring\n</thinking>\nafter")
        events += p.finalize()
        thinking = "".join(t for k, t in events if k == "thinking")
        text = "".join(t for k, t in events if k == "text")
        assert "during" in thinking
        assert "before" in text and "after" in text

    def test_empty_thinking_block(self):
        p = ThinkingStreamParser()
        events = p.feed("<thinking>\n</thinking>\ntext")
        events += p.finalize()
        text = "".join(t for k, t in events if k == "text")
        assert "text" in text

    def test_character_by_character(self):
        p = ThinkingStreamParser()
        full = "<thinking>\nabc\n</thinking>\nxyz"
        events = []
        for ch in full:
            events += p.feed(ch)
        events += p.finalize()
        thinking = "".join(t for k, t in events if k == "thinking")
        text = "".join(t for k, t in events if k == "text")
        assert "abc" in thinking
        assert "xyz" in text

    def test_newlines_preserved(self):
        p = ThinkingStreamParser()
        events = p.feed("<thinking>\nline1\nline2\n</thinking>")
        events += p.finalize()
        thinking = "".join(t for k, t in events if k == "thinking")
        assert "line1\nline2" in thinking

    def test_full_thinking_text_property(self):
        p = ThinkingStreamParser()
        p.feed("<thinking>\npart1\n</thinking>\ngap\n<thinking>\npart2\n</thinking>\nend")
        assert "part1" in p.full_thinking_text
        assert "part2" in p.full_thinking_text


class TestLoopDetector:
    def test_no_repetition(self):
        d = LoopDetector()
        assert not d.feed("Normal text without any repeating patterns at all here.")

    def test_short_text(self):
        d = LoopDetector()
        assert not d.feed("abc" * 10)

    def test_long_repeating_pattern(self):
        d = LoopDetector()
        pattern = "I need to analyze this carefully now. ok " * 10
        assert d.feed(pattern)

    def test_incremental_detection(self):
        d = LoopDetector()
        pattern = "I keep repeating this same thought!! "
        for _ in range(6):
            assert not d.feed(pattern)
        for _ in range(6):
            if d.feed(pattern):
                return
        assert False, "Should have detected loop"


class TestStripThinkingTags:
    def test_basic(self):
        assert strip_thinking_tags("<thinking>\nr\n</thinking>\nanswer") == "answer"

    def test_multiline(self):
        result = strip_thinking_tags("<thinking>\nline1\nline2\n</thinking>\nanswer")
        assert result == "answer"

    def test_multiple_blocks(self):
        result = strip_thinking_tags("<thinking>\na\n</thinking>\nX\n<thinking>\nb\n</thinking>\nY")
        assert "X" in result
        assert "Y" in result
        assert "a" not in result
        assert "b" not in result

    def test_no_tags(self):
        assert strip_thinking_tags("just text") == "just text"

    def test_unclosed_block(self):
        result = strip_thinking_tags("<thinking>\nunclosed reasoning")
        assert result == ""

    def test_model_mentions_closing_tag_inside(self):
        text = (
            "<thinking>\n"
            "use </thinking> to end a block\n"
            "more reasoning\n"
            "</thinking>\n"
            "answer"
        )
        result = strip_thinking_tags(text)
        assert "answer" in result
        assert "reasoning" not in result


class TestStripThinkingFromMessages:
    def test_strip_assistant(self):
        from bouzecode.backend.agent.minimal_payload import _strip_thinking_from_messages
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "<thinking>\nr\n</thinking>\nanswer"},
        ]
        result = _strip_thinking_from_messages(msgs)
        assert result[0]["content"] == "hi"
        assert "answer" in result[1]["content"]

    def test_user_unchanged(self):
        from bouzecode.backend.agent.minimal_payload import _strip_thinking_from_messages
        msgs = [{"role": "user", "content": "about thinking tags"}]
        result = _strip_thinking_from_messages(msgs)
        assert result[0]["content"] == "about thinking tags"

    def test_empty_after_strip_uses_placeholder(self):
        from bouzecode.backend.agent.minimal_payload import _strip_thinking_from_messages
        msgs = [{"role": "assistant", "content": "<thinking>\nonly thinking\n</thinking>"}]
        result = _strip_thinking_from_messages(msgs)
        assert result[0]["content"] == "."

    def test_multiline_thinking(self):
        from bouzecode.backend.agent.minimal_payload import _strip_thinking_from_messages
        msgs = [{"role": "assistant", "content": "<thinking>\nline1\nline2\n</thinking>\nanswer"}]
        result = _strip_thinking_from_messages(msgs)
        assert result[0]["content"].strip() == "answer"

    def test_multiple_blocks(self):
        from bouzecode.backend.agent.minimal_payload import _strip_thinking_from_messages
        msgs = [{"role": "assistant", "content": "<thinking>\na\n</thinking>\nX\n<thinking>\nb\n</thinking>\nY"}]
        result = _strip_thinking_from_messages(msgs)
        assert "X" in result[0]["content"]
        assert "Y" in result[0]["content"]
