# [desc] Verrou : /image est atteignable, rend la sentinelle __image__ et écrit sur la config vivante. [/desc]
"""`/image` must be reachable, not merely implemented.

`cmd_image` was imported by `dispatcher.py` and left out of `COMMANDS`, so typing
`/image` printed "Unknown command". The tests go through `handle_slash`, the REPL's own
entry point, and check the tuple handed back — the contract of a sentinel command.

The one effect a test can neither provoke nor predict is the system clipboard, read
through Pillow, which is an optional extra and may be absent altogether. So `PIL` and
`PIL.ImageGrab` are supplied as hand-written fake modules holding whatever the test
decides the clipboard contains — plain objects, no `unittest.mock`. Everything else runs
for real: the dispatcher, the PNG buffering, the base64 encoding and the config write.
"""
from __future__ import annotations

import base64
import inspect
import sys
import types

import pytest

from bouzecode.backend.commands.dispatcher import COMMANDS, handle_slash

DEFAULT_PROMPT = "What do you see in this image? Describe it in detail."


class _ClipboardImage:
    """The whole surface `cmd_image` uses: a size, and a save() that writes bytes."""

    size = (12, 34)
    payload = b"the-bytes-a-real-encoder-would-have-produced"

    def save(self, buffer, format):  # noqa: A002 — Pillow's own keyword name
        assert format == "PNG"
        buffer.write(self.payload)


@pytest.fixture
def clipboard(monkeypatch):
    """Install a fake `PIL.ImageGrab` returning the image the test chooses (or None)."""
    def _holding(image):
        grab = types.ModuleType("PIL.ImageGrab")
        grab.grabclipboard = lambda: image
        pil = types.ModuleType("PIL")
        pil.ImageGrab = grab
        monkeypatch.setitem(sys.modules, "PIL", pil)
        monkeypatch.setitem(sys.modules, "PIL.ImageGrab", grab)

    return _holding


def test_slash_image_returns_the_sentinel_with_a_default_prompt(clipboard):
    clipboard(_ClipboardImage())

    assert handle_slash("/image", None, {}) == ("__image__", DEFAULT_PROMPT)


def test_slash_image_forwards_its_arguments_as_the_prompt(clipboard):
    """The text after the command name reaches the handler and becomes the question."""
    clipboard(_ClipboardImage())

    assert handle_slash("/image  what colour is the car? ", None, {}) == (
        "__image__", "what colour is the car?",
    )


def test_slash_image_puts_the_encoded_capture_on_the_live_config(clipboard):
    """The dispatcher passes the caller's config, so the model sees the same image."""
    clipboard(_ClipboardImage())
    config = {"model": "a-model"}

    handle_slash("/image", None, config)

    assert base64.b64decode(config["_pending_image"]) == _ClipboardImage.payload


def test_slash_image_reports_an_empty_clipboard_instead_of_a_sentinel(clipboard, capsys):
    """Nothing to send: handled, and the loop is given nothing to run."""
    clipboard(None)

    assert handle_slash("/image", None, {}) is True
    assert "No image found in clipboard" in capsys.readouterr().err


def test_help_lists_image(capsys):
    """`/help` prints `_CMD_META`, so a wired command must appear there."""
    handle_slash("/help", None, {})

    assert "/image" in capsys.readouterr().out


def test_image_handler_matches_the_dispatcher_calling_convention():
    """`handle_slash` calls `handler(args, state, config)` positionally."""
    parameters = list(inspect.signature(COMMANDS["image"]).parameters.values())

    assert len(parameters) == 3
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in parameters)
