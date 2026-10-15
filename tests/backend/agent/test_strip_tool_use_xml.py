"""Regression tests for strip_tool_use_xml (session persistence cleaning).

Bug: an assistant message that MENTIONS a tool tag in its prose was destroyed
when saved: the whole reasoning block and part of the prose vanished, and the
persisted content ended up being "." or a 10-char residue. Root cause was that
strip_tool_use_xml fed a full message to a STREAMING parser, whose leftover
buffer is dropped by finalize().

Tags are built by concatenation on purpose: writing a literal complete tag in
this file would corrupt the very stream that generates it.
"""
from bouzecode.backend.agent.thinking_parser import strip_tool_use_xml

TU_OPEN = "<" + 'tool_use name="Bash" id="b1">'
TU_CLOSE = "</" + "tool_use>"
TC_OPEN = "<" + "tool_calls>"
TC_CLOSE = "</" + "tool_calls>"
TH_OPEN = "<" + "thinking>"
TH_CLOSE = "</" + "thinking>"
CD_OPEN = "<!" + "[CDATA["
CD_CLOSE = "]]" + ">"

REASONING = "Je verifie la cause du bug avant de corriger."
BATCH = (
    TC_OPEN + "\n"
    + TU_OPEN + '<param name="command">echo hi</param>' + TU_CLOSE + "\n"
    + TC_CLOSE
)


def _message(prose: str, batch: str = BATCH) -> str:
    return (
        TH_OPEN + "\n  " + REASONING + "\n" + TH_CLOSE + "\n\n"
        + prose + "\n\n"
        + batch
    )


def test_real_tool_block_removed_but_reasoning_and_prose_kept():
    out = strip_tool_use_xml(_message("Je corrige le bug de config."))
    assert REASONING in out
    assert "Je corrige le bug de config." in out
    assert "echo hi" not in out


def test_mention_of_batch_close_tag_in_prose_does_not_eat_content():
    prose = "Le batch se termine par " + TC_CLOSE + " et rien apres."
    out = strip_tool_use_xml(_message(prose))
    assert REASONING in out, "reasoning was swallowed by the tool-tag mention"
    assert "Le batch se termine par" in out
    assert "et rien apres." in out
    assert "echo hi" not in out


def test_mention_of_tool_open_tag_in_prose_does_not_eat_content():
    prose = "On ecrit " + TU_OPEN + " pour appeler un outil."
    out = strip_tool_use_xml(_message(prose))
    assert REASONING in out
    assert "On ecrit" in out
    assert "pour appeler un outil." in out
    assert "echo hi" not in out


def test_mention_inside_cdata_of_a_real_block_is_removed_with_it():
    batch = (
        TC_OPEN + "\n"
        + TU_OPEN + '<param name="content">' + CD_OPEN
        + "doc mentioning " + TU_CLOSE + CD_CLOSE + "</param>" + TU_CLOSE + "\n"
        + TC_CLOSE
    )
    out = strip_tool_use_xml(_message("Prose visible ici.", batch=batch))
    assert REASONING in out
    assert "Prose visible ici." in out
    assert "doc mentioning" not in out


def test_message_without_tool_use_is_untouched():
    content = TH_OPEN + "\n  " + REASONING + "\n" + TH_CLOSE + "\n\nJuste de la prose."
    assert strip_tool_use_xml(content) == content.strip()


def test_reasoning_only_message_never_becomes_empty():
    """No prose at all: the reasoning must survive, otherwise the saver wrote "."."""
    content = TH_OPEN + "\n  " + REASONING + "\n" + TH_CLOSE + "\n\n" + BATCH
    out = strip_tool_use_xml(content)
    assert out.strip() not in ("", ".")
    assert REASONING in out


def test_unmatched_tool_open_is_kept_as_plain_text():
    content = "Une phrase avec " + TU_OPEN + " jamais fermee, puis la suite du texte."
    out = strip_tool_use_xml(content)
    assert "Une phrase avec" in out
    assert "puis la suite du texte." in out
