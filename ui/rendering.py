# [desc] Streams and renders LLM response text to the terminal using Rich live display with overflow handling. [/desc]
# [desc] Streams and renders LLM response text to the terminal using Rich live display with overflow handling. [/desc]
from __future__ import annotations
import sys
from ui.ansi import C

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


def _make_renderable(text: str):
    if any(c in text for c in ("#", "*", "`", "_", "[")):
        return Markdown(text)
    return text

def _start_live() -> None:
    global _current_live
    if _RICH and _RICH_LIVE and _current_live is None:
        _current_live = Live(console=console, auto_refresh=False,
                             vertical_overflow="visible")
        _current_live.start()

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
    if not line.strip():
        console.print()
    else:
        console.print(_make_renderable(line))


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
            _current_live.update(_make_renderable(full), refresh=True)
        elif rendered_lines <= threshold:
            _start_live()
            _current_live.update(_make_renderable(full), refresh=True)
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

def stream_thinking(chunk: str, verbose: bool):
    if verbose:
        clean_chunk = chunk.replace("\n", " ")
        if clean_chunk:
            print(f"{C['dim']}{clean_chunk}", end="", flush=True)

def flush_response() -> None:
    global _current_live, _live_overflow
    full = "".join(_accumulated_text)
    _accumulated_text.clear()
    if _current_live is not None:
        _current_live.stop()
        _current_live = None
    elif _live_overflow and _RICH:
        remaining = "".join(_overflow_lines_buf).rstrip()
        _overflow_lines_buf.clear()
        if remaining:
            console.print(_make_renderable(remaining))
        else:
            console.print()
    elif _live_overflow:
        print()
    elif _RICH and _RICH_LIVE and full.strip():
        console.print(_make_renderable(full))
    else:
        print()
    _live_overflow = False
    _overflow_lines_buf.clear()
