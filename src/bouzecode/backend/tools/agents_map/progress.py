"""Progress feedback for the (single, monolithic) LLM regeneration of SymbolMap /
AgentsMap.

There is no per-file loop to measure, but the ONE `client.messages.stream` call
produces the whole map token by token. The honest, RELEVANT signal is therefore the
size of the document AS IT IS BEING WRITTEN — "SymbolMap: sessions — 34 lignes" — not
an elapsed-second heartbeat that says nothing about the actual work.

Why full text lines (`\n`) and not a `\r` spinner: the agent subprocess merges
stdout+stderr into its `.out.log`, which the web streams over SSE. That stream
FILTERS carriage-return spinner frames and blank lines (`_SPINNER_RE`), so a `tqdm`
animation would be invisible on the web. A complete text line per update passes the
filter and is legible on BOTH surfaces (terminal TUI + web) with a single mechanism.
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Callable, IO, Iterator


@contextmanager
def progress_reporter(
    label: str, stream: IO[str] | None = None, min_interval: float = 0.5,
) -> Iterator[Callable[[str], None]]:
    """Yield a `report(accumulated_text)` callback that emits, at most once every
    `min_interval` seconds, `f"{label} — {n} lignes\\n"` where `n` is the number of
    NON-EMPTY lines produced so far.

    Throttling matters: `text_stream` yields many tiny deltas per second; emitting a
    line for each would flood the log. One line per `min_interval` is a legible pace
    that still shows the document growing. A map served from a fresh cache never calls
    `report` (no stream happens), so it stays SILENT — no heartbeat for finished work.

    No thread: the stream loop itself is the heartbeat; `report` is called
    synchronously from within it.
    """
    out = stream if stream is not None else sys.stderr
    last = 0.0
    last_n = -1

    def report(acc_text: str) -> None:
        nonlocal last, last_n
        now = time.monotonic()
        if now - last < min_interval:
            return
        n = sum(1 for line in acc_text.splitlines() if line.strip())
        if n == last_n:
            return  # nothing new to say since the last emitted line
        last = now
        last_n = n
        try:
            out.write(f"{label} — {n} lignes\n")
            out.flush()
        except (ValueError, OSError):
            # Stream closed underneath us (subprocess tearing down): stop quietly.
            pass

    yield report
