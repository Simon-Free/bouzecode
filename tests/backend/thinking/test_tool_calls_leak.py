# [desc] Regression test proving the `ool_calls>` leak disappears once a sloppy `</thinking>` close is accepted. [/desc]
"""The reported symptom was a visible line starting with `ool_calls>` — i.e.
`` amputated of its first two chars.

Root cause is the SAME as the sloppy-close bug: while the close was refused,
the parser stayed in thinking mode; the only retainable suffix of a buffer
ending with `... </thinking> ou <t` is `<` (because `<t` is not a prefix of
`</thinking>`), so the `t` was flushed INSIDE the thinking stream (hidden from
display) and the next chunk emitted `ool_calls>` as visible text.

Once the close is accepted, the parser is back in text mode where the retained
prefix is computed against `<thinking>` — `<t` IS a valid prefix there, so the
tag survives intact.
"""
from bouzecode.backend.agent.thinking_parser import ThinkingStreamParser


def _run(chunks: list[str]) -> list[tuple[str, str]]:
    parser = ThinkingStreamParser()
    out: list[tuple[str, str]] = []
    for chunk in chunks:
        out += parser.feed(chunk)
    out += parser.finalize()
    return out


def _merge(results: list[tuple[str, str]], kind: str) -> str:
    return "".join(text for k, text in results if k == kind)


def test_tool_calls_tag_not_amputated_after_sloppy_close():
    """Exact user-reported sequence: nothing lost, nothing duplicated."""
    results = _run([
        "<thinking>\n",
        "Etape decisive : grep cible.\n</thinking> ou <t",
        "ool_calls>\n",
    ])
    thinking = _merge(results, "thinking")
    text = _merge(results, "text")

    # The newline right after <thinking> belongs to the thought (OPEN_TAG
    # does not swallow it) — historical, stable contract of the parser.
    assert thinking == "\nEtape decisive : grep cible.\n"
    # `<t` stays in the TEXT stream (retained as a possible `<thinking>` prefix)
    # and is completed at the next chunk: the tag comes out WHOLE, not amputated.
    assert text == " ou " + "<tool" + "_calls>" + "\n"
    # The amputated form must never reach the visible stream
    assert not text.lstrip().startswith("ool_calls>")
    assert "</thinking>" not in text


def test_tool_calls_tag_split_at_every_offset():
    """Whatever the chunk boundary, the visible text is reassembled verbatim."""
    payload = "<thinking>\nThought.\n</thinking> tail \n"
    for cut in range(1, len(payload)):
        results = _run([payload[:cut], payload[cut:]])
        assert _merge(results, "text") == " tail \n", f"cut={cut}"
        assert _merge(results, "thinking") == "\nThought.\n", f"cut={cut}"
