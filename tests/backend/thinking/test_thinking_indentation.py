# [desc] Tests indentation-based thinking block parsing rules for open/close tag detection
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests indentation-based thinking block parsing rules for open/close tag detection</param></tool_use> [/desc]
"""Tests for thinking indentation-based parsing rules.

The model MUST indent thinking content by 2 spaces. Only </thinking> at column 0
(no leading whitespace) closes a thinking block. This prevents false closures when
the model mentions </thinking> inside its reasoning.
"""
from bouzecode.backend.agent.thinking_parser import ThinkingStreamParser, strip_thinking_tags
from bouzecode.backend.xml_tool_protocol.parser import _is_in_thinking


class TestThinkingStreamParserIndentation:
    def test_indented_close_tag_does_not_close(self):
        parser = ThinkingStreamParser()
        chunks = parser.feed("<thinking>\n  Le parser utilise </thinking> pour fermer\n</thinking>\n")
        thinking_chunks = [(k, t) for k, t in chunks if k == "thinking"]
        thinking_content = "".join(t for _, t in thinking_chunks)
        # The indented </thinking> should NOT close the block — it's part of the thinking content
        assert "</thinking>" in thinking_content
        assert "</thinking> pour fermer" in parser.full_thinking_text

    def test_column_zero_close_tag_closes(self):
        parser = ThinkingStreamParser()
        chunks = parser.feed("<thinking>\n  some reasoning\n</thinking>\nreal text")
        kinds = [kind for kind, _ in chunks]
        assert "text" in kinds
        text_parts = "".join(t for k, t in chunks if k == "text")
        assert "real text" in text_parts

    def test_indented_open_tag_not_recognized(self):
        parser = ThinkingStreamParser()
        chunks = parser.feed("hello\n  <thinking>\nstill text\n")
        # Indented <thinking> should not start a block
        kinds = [kind for kind, _ in chunks]
        assert all(k == "text" for k in kinds)

    def test_nested_mention_in_thinking(self):
        content = (
            "<thinking>\n"
            "  L'utilisateur veut que </thinking> indenté ne ferme pas.\n"
            "  Testons aussi <thinking> indenté.\n"
            "</thinking>\n"
            "Résultat final"
        )
        parser = ThinkingStreamParser()
        chunks = parser.feed(content)
        chunks += parser.finalize()
        text_parts = "".join(t for k, t in chunks if k == "text")
        assert "Résultat final" in text_parts
        assert "</thinking> indenté ne ferme pas" in parser.full_thinking_text


class TestStripThinkingTagsIndentation:
    def test_indented_close_tag_not_stripped(self):
        content = (
            "<thinking>\n"
            "  Voici du contenu avec </thinking> dedans\n"
            "</thinking>\n"
            "Texte visible"
        )
        result = strip_thinking_tags(content)
        assert result == "Texte visible"

    def test_indented_open_tag_not_stripped(self):
        content = (
            "Normal text\n"
            "  <thinking>\n"
            "This is NOT thinking\n"
            "  </thinking>\n"
            "More text"
        )
        result = strip_thinking_tags(content)
        # Indented <thinking> should be kept as regular text
        assert "<thinking>" in result
        assert "This is NOT thinking" in result

    def test_column_zero_tags_work(self):
        content = (
            "<thinking>\n"
            "  Hidden reasoning\n"
            "</thinking>\n"
            "Visible result"
        )
        result = strip_thinking_tags(content)
        assert result == "Visible result"
        assert "Hidden reasoning" not in result

    def test_multiple_blocks_with_indented_mentions(self):
        content = (
            "<thinking>\n"
            "  Block 1 mentions </thinking> but indented\n"
            "</thinking>\n"
            "Between blocks\n"
            "<thinking>\n"
            "  Block 2\n"
            "</thinking>\n"
            "Final"
        )
        result = strip_thinking_tags(content)
        assert "Between blocks" in result
        assert "Final" in result
        assert "Block 1" not in result
        assert "Block 2" not in result


class TestIsInThinkingIndentation:
    def test_indented_close_tag_stays_in_thinking(self):
        buf = "<thinking>\n  some text with </thinking> indented\n</thinking>\nafter"
        # Position inside the indented </thinking> — should still be in thinking
        pos = buf.index("some text")
        result = _is_in_thinking(buf, pos)
        assert result is not None
        # The close should be at the column-0 </thinking>
        real_close = buf.index("\n</thinking>") + 1  # position of < after \n
        expected_end = real_close + len("</thinking>")
        assert result == (expected_end,)

    def test_column_zero_close_works(self):
        buf = "<thinking>\n  reasoning\n</thinking>\ntext"
        pos = 15  # inside thinking
        result = _is_in_thinking(buf, pos)
        assert result is not None
        close_end = buf.index("</thinking>") + len("</thinking>")
        assert result == (close_end,)

    def test_position_after_thinking_block_not_in_thinking(self):
        buf = "<thinking>\n  reasoning\n</thinking>\ntext after"
        pos = buf.index("text after")
        result = _is_in_thinking(buf, pos)
        assert result is None

    def test_unclosed_with_indented_close(self):
        buf = "<thinking>\n  has </thinking> indented but no real close"
        pos = 5
        result = _is_in_thinking(buf, pos)
        # No column-0 close → unclosed
        assert result == (-1,)
