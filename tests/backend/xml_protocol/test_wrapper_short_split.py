"""Le wrapper <tool_calls> coupé COURT entre deux chunks ne doit jamais fuiter.

La session web f52cb5297f4f a produit ~115 messages assistant dont le content
est exactement ``ool_calls>`` : le tag ``<tool_calls>`` arrivait coupé après
1 à 6 caractères (ex. ``<t`` | ``ool_calls>``), sous le seuil de rétention du
parser, et le fragment passait dans le texte visible.

Ces tests rejouent ces coupes courtes et exigent : zéro fragment de wrapper
dans le texte visible, appels toujours extraits, prose « 3 < 5 » intacte.
"""

from tests.backend.xml_protocol.test_tool_calls_wrapper import BATCH, _feed, _parser


def test_short_split_of_open_wrapper_leaks_nothing():
    """Coupe l'ouverture après 1..6 chars : le tag reconstitué doit disparaître."""
    for cut in range(1, 7):  # "<" .. "<tool_"
        calls, texts = _feed(
            _parser(),
            BATCH[:cut],
            BATCH[cut:],
        )
        assert [c["name"] for c in calls] == ["Read", "Bash"], f"cut={cut}: appels perdus"
        joined = "".join(texts)
        assert "tool_calls" not in joined, f"cut={cut}: fuite open -> {joined!r}"
        assert joined.strip() == "", f"cut={cut}: résidu -> {joined!r}"


def test_short_split_of_close_wrapper_leaks_nothing():
    """Coupe la fermeture après 1..7 chars : idem côté </tool_calls>."""
    close_at = len(BATCH) - len("</tool_calls>")
    for cut in range(1, 8):  # "<" .. "</tool_"
        calls, texts = _feed(
            _parser(),
            BATCH[: close_at + cut],
            BATCH[close_at + cut :],
        )
        assert [c["name"] for c in calls] == ["Read", "Bash"], f"cut={cut}: appels perdus"
        joined = "".join(texts)
        assert "tool_calls" not in joined, f"cut={cut}: fuite close -> {joined!r}"
        assert "lls>" not in joined, f"cut={cut}: fuite close -> {joined!r}"
        assert joined.strip() == "", f"cut={cut}: résidu -> {joined!r}"


def test_session_fragment_repro():
    """Repro exact de la session : '<t' | 'ool_calls>...' ne doit rien laisser fuiter."""
    stream = (
        "<t",
        "ool_calls>\n"
        '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
        "</tool_calls>",
    )
    calls, texts = _feed(_parser(), *stream)
    assert [c["name"] for c in calls] == ["Read"]
    joined = "".join(texts)
    assert "ool_calls" not in joined, f"fragment de session -> {joined!r}"
    assert joined.strip() == "", f"résidu -> {joined!r}"


def test_trailing_lt_in_prose_is_not_swallowed():
    """Un '<' de prose ('3 < 5') ne doit être ni avalé ni retardé indûment."""
    calls, texts = _feed(_parser(), "3 <", " 5")
    assert calls == []
    assert "".join(texts) == "3 < 5"


def test_stream_ending_on_pending_flushes_it_as_text():
    """Un stream qui FINIT sur un '<' potentiel : finalize doit le rendre, pas le jeter."""
    parser = _parser()
    items = parser.feed("x <")
    items.extend(parser.finalize())
    texts = [i for i in items if isinstance(i, str)]
    assert "".join(texts) == "x <"
