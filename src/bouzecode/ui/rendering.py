# [desc] Streams and renders LLM response text to the terminal using Rich live display with overflow handling. [/desc]
from __future__ import annotations
import re
import sys
from .ansi import C
from .barre_agents.rendu import (
    avec_pied, bloc_pied, effacement, fin_de_pensee, lignes_pied, penser,
)

# Rich Markdown silently strips <param …> tags (keeping their text), collapsing a
# well-formed tool call into an unreadable concatenated blob, while leaving
# <tool_use …> visible. Any tool-protocol markup that reaches visible text (e.g.
# the model illustrating a planned call in its prose/thinking) is entity-escaped
# below so Markdown renders it verbatim instead of mangling it.
_TOOL_MARKUP_RE = re.compile(r"</?(?:tool_use|param)\b[^>]*>")

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.live import Live
    from rich.syntax import Syntax
    from rich.panel import Panel
    from rich import print as rprint
    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None

_accumulated_text: list[str] = []
_current_live: "Live | None" = None
_live_overflow = False
_overflow_lines_buf: list[str] = []
_RICH_LIVE = True


def _neutralize_tool_markup(text: str) -> str:
    """Entity-escape stray <tool_use>/<param> markup so Markdown shows it verbatim."""
    return _TOOL_MARKUP_RE.sub(
        lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"), text
    )


def _make_renderable(text: str):
    if any(c in text for c in ("#", "*", "`", "_", "[")):
        return Markdown(_neutralize_tool_markup(text))
    return text


def safe_print(renderable, fallback: str = "") -> None:
    """`console.print` that can never abort the turn.

    Rich renders fenced code blocks through `rich.syntax.Syntax`, which resolves its
    theme with `pygments.styles.get_style_by_name()` — at PRINT time, not import time.
    A broken/partial pygments install therefore raises (e.g. `ClassNotFound: Could not
    find style module 'pygments.styles.default', though it should be builtin`) deep
    inside display code and used to surface as "Turn aborted due to an unhandled
    error". The `try: from rich ... except ImportError` guard above cannot catch that.
    Losing colours is acceptable; losing the turn is not — so degrade to plain text.
    """
    if console is not None:
        try:
            console.print(renderable)
            return
        except Exception:
            pass
    text = fallback if fallback else (renderable if isinstance(renderable, str) else "")
    print(text, flush=True)


def _safe_live_update(live, renderable, fallback: str) -> None:
    """`Live.update` that degrades to plain stdout instead of killing the turn.

    A render failure inside a Live region cannot be retried in place (the region is
    left half-drawn), so rich is disabled for the rest of the session and the text is
    dumped raw — subsequent chunks then take the plain `print` path in `stream_text`.
    """
    global _RICH_LIVE, _current_live
    try:
        live.update(renderable, refresh=True)
        return
    except Exception:
        pass
    _RICH_LIVE = False
    try:
        live.stop()
    except Exception:
        pass
    _current_live = None
    print(fallback, flush=True)

def _start_live() -> None:
    global _current_live
    if _RICH and _RICH_LIVE and _current_live is None:
        _current_live = Live(console=console, auto_refresh=False,
                             vertical_overflow="visible")
        _current_live.start()
        # Live a pose son FileProxy sur sys.stdout : un sous-agent y écrirait chez main.
        from bouzecode.backend.core.sortie_agent import reposer
        reposer()

def _estimate_rendered_lines(text: str, width: int) -> int:
    total = 0
    for line in text.split("\n"):
        total += max(1, -(-len(line) // width))
    return total

def _erase_lines(count: int) -> None:
    for _ in range(count):
        sys.stdout.write("\033[A")
        sys.stdout.write("\033[2K")
    sys.stdout.write("\r")
    sys.stdout.flush()

def _flush_overflow_line(line: str) -> None:
    _ecrire(effacement(""))  # la barre des sous-agents se redessine SOUS chaque ligne
    if not line.strip():
        console.print()
    else:
        safe_print(_make_renderable(line), line)
    _ecrire(bloc_pied())


def stream_text(chunk: str) -> None:
    global _current_live, _live_overflow
    _accumulated_text.append(chunk)
    if _RICH and _RICH_LIVE and not _live_overflow:
        full = "".join(_accumulated_text)
        term_height = console.height if console else 40
        term_width = console.width if console else 80
        rendered_lines = _estimate_rendered_lines(full, term_width)
        threshold = int(term_height * 0.6)
        if _current_live is not None and rendered_lines > threshold:
            _current_live.update("", refresh=True)
            _current_live.stop()
            _current_live = None
            _live_overflow = True
            _overflow_lines_buf.clear()
            lines = full.split("\n")
            for line in lines[:-1]:
                _flush_overflow_line(line)
            _overflow_lines_buf.append(lines[-1])
        elif _current_live is not None:
            _safe_live_update(_current_live, avec_pied(_make_renderable(full)), full)
        elif rendered_lines <= threshold:
            _start_live()
            _safe_live_update(_current_live, avec_pied(_make_renderable(full)), full)
        else:
            _live_overflow = True
            _overflow_lines_buf.clear()
            lines = full.split("\n")
            for line in lines[:-1]:
                _flush_overflow_line(line)
            _overflow_lines_buf.append(lines[-1])
    elif _live_overflow and _RICH:
        _overflow_lines_buf.append(chunk)
        buf = "".join(_overflow_lines_buf)
        if "\n" in buf:
            lines = buf.split("\n")
            for line in lines[:-1]:
                _flush_overflow_line(line)
            _overflow_lines_buf.clear()
            _overflow_lines_buf.append(lines[-1])
    else:
        print(chunk, end="", flush=True)

def _ecrire(texte: str) -> None:
    print(texte, end="", flush=True)


def stream_thinking(chunk: str):
    if chunk and not penser(chunk, _ecrire):  # barre des sous-agents : sous les lignes
        print(f"\033[3;2m{chunk}", end="", flush=True)

def end_thinking_block():
    fin_de_pensee(_ecrire)
    print("\033[0m", end="", flush=True)

def flush_response() -> None:
    global _current_live, _live_overflow
    full = "".join(_accumulated_text)
    _accumulated_text.clear()
    _ecrire(effacement(""))  # barre dessinee sous des lignes debordantes : effacee
    if _current_live is not None:
        # Dernier rendu SANS la barre : Live le laisse a l'ecran en s'arretant.
        if lignes_pied():
            _current_live.update(_make_renderable(full), refresh=True)
        _current_live.stop()
        _current_live = None
    elif _live_overflow and _RICH:
        remaining = "".join(_overflow_lines_buf).rstrip()
        _overflow_lines_buf.clear()
        if remaining:
            safe_print(_make_renderable(remaining), remaining)
        else:
            console.print()
    elif _live_overflow:
        print()
    elif _RICH and _RICH_LIVE and full.strip():
        safe_print(_make_renderable(full), full)
    else:
        print()
    _live_overflow = False
    _overflow_lines_buf.clear()
