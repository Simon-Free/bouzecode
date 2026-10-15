# [desc] Tests du proxy stdout/stderr qui efface la ligne du spinner avant chaque log (modèle tqdm.write) [/desc]
"""The spinner holds a LIVE line: it rewrites it with `\\r` and never emits a newline.
Any other writer (`[map] miss ...` on stderr, a plain `print` on stdout) knows nothing
about it, so on a terminal both land on the same physical line:

    ⠙ 🤔 Who is Barry Allen?...   [map] miss    SymbolMap work — 1 fichier(s) ...

The fix is the `tqdm.write` model: while the spinner runs, stdout and stderr are wrapped
so that a write ERASES the spinner line first; the next tick redraws it below the log.
"""
import io
import sys

from bouzecode.ui import spinner


def test_text_write_erases_the_spinner_line_first():
    real, erase = io.StringIO(), io.StringIO()
    stream = spinner._SpinnerAwareStream(real, erase)

    stream.write("[map] miss    SymbolMap work\n")

    erased = erase.getvalue()
    assert erased.startswith("\r"), erased
    assert erased.endswith("\r"), erased
    assert erased.strip("\r") == " " * len(erased.strip("\r"))
    assert real.getvalue() == "[map] miss    SymbolMap work\n"


def test_spinner_own_frames_are_not_erased():
    """Frames start with `\\r`: they must pass through untouched, or the proxy would
    erase the very line it is about to draw (and recurse forever)."""
    real, erase = io.StringIO(), io.StringIO()
    stream = spinner._SpinnerAwareStream(real, erase)

    stream.write("\r  \u280b thinking...   ")

    assert erase.getvalue() == ""
    assert real.getvalue() == "\r  \u280b thinking...   "


def test_empty_write_erases_nothing():
    real, erase = io.StringIO(), io.StringIO()
    stream = spinner._SpinnerAwareStream(real, erase)

    stream.write("")

    assert erase.getvalue() == ""


def test_proxy_delegates_flush_and_attributes():
    real, erase = io.StringIO(), io.StringIO()
    stream = spinner._SpinnerAwareStream(real, erase)

    stream.flush()  # must not raise
    assert stream.getvalue() == ""  # __getattr__ delegation


def test_start_wraps_both_streams_and_stop_restores_them():
    out, err = sys.stdout, sys.stderr
    spinner._start_tool_spinner()
    try:
        assert isinstance(sys.stdout, spinner._SpinnerAwareStream)
        assert isinstance(sys.stderr, spinner._SpinnerAwareStream)
    finally:
        spinner._stop_tool_spinner()

    assert sys.stdout is out
    assert sys.stderr is err


def test_start_is_idempotent_and_does_not_stack_proxies():
    out = sys.stdout
    spinner._start_tool_spinner()
    try:
        first = sys.stdout
        spinner._start_tool_spinner()
        assert sys.stdout is first
    finally:
        spinner._stop_tool_spinner()
    assert sys.stdout is out


def test_spinner_writes_to_the_real_stream_not_through_the_proxy():
    """The animation must target the captured real stdout: if it went through the proxy
    it would be indistinguishable from a log line."""
    fake = io.StringIO()
    original = sys.stdout
    sys.stdout = fake
    try:
        spinner._start_tool_spinner()
        assert spinner._spinner_out is fake
    finally:
        spinner._stop_tool_spinner()
        sys.stdout = original


def test_progression_refused_without_a_running_spinner():
    """No spinner (web agent, plain CLI): the caller falls back to stderr."""
    assert spinner.afficher_progression("pytest: 1/3") is False


def test_progression_replaces_the_phrase_until_the_next_step():
    fake = io.StringIO()
    original = sys.stdout
    sys.stdout = fake
    try:
        spinner._start_tool_spinner()
        assert spinner.afficher_progression("pytest: 2/3") is True
        for _ in range(50):  # the next frame (100 ms) draws it; 5 s at most
            if "pytest: 2/3" in fake.getvalue():
                break
            spinner._tool_spinner_stop.wait(0.1)
        assert "pytest: 2/3" in fake.getvalue()
        spinner._change_spinner_phrase()  # ToolEnd: next step, the progress is gone
        assert spinner._spinner_progression == ""
    finally:
        spinner._stop_tool_spinner()
        sys.stdout = original
