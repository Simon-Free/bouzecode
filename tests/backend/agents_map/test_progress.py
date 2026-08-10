"""La régénération d'un SymbolMap/AgentsMap doit rendre compte de sa PROGRESSION RÉELLE
(le document qui se construit, mesuré en lignes), pas d'un simple compteur de secondes.

Contrat vérifié sans mock du réseau : un faux client qui STREAME sa réponse déclenche
`on_delta` à chaque delta → `generate_symbols` émet des lignes « SymbolMap: <dir> — N
lignes » sur le flux capturé. Un faux client sans `stream` (ceux du reste de la suite)
retombe sur le chemin bloquant, sans planter et sans rien émettre.
"""
from __future__ import annotations

import io
import time
from contextlib import contextmanager
from pathlib import Path

from bouzecode.backend.tools.agents_map import regen
from bouzecode.backend.tools.agents_map.progress import progress_reporter


_DOC = "\n".join(f"line-{i}  L{i}-{i + 1}" for i in range(1, 21))


class _StreamCtx:
    def __init__(self, text: str):
        self._chunks = [text[i:i + 4] for i in range(0, len(text), 4)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        yield from self._chunks


class _StreamingClient:
    """Faux client qui STREAME : expose `messages.stream` comme le vrai SDK Anthropic."""

    def __init__(self, text: str):
        self._text = text
        self.messages = self

    def stream(self, **kwargs):
        return _StreamCtx(self._text)


class _BlockingClient:
    """Faux client SANS `stream` (comme FakeLLM du reste de la suite) : que `create`."""

    def __init__(self, text: str):
        self._text = text
        self.messages = self

    def create(self, **kwargs):
        return type("R", (), {
            "content": [type("B", (), {"type": "text", "text": self._text})()],
        })()


def test_streaming_client_reports_growing_line_count(monkeypatch):
    buf = io.StringIO()

    # progress_reporter écrit sur sys.stderr par défaut ; on capture via un stderr factice
    # tout en gardant un min_interval nul pour observer chaque palier.
    real_reporter = progress_reporter

    @contextmanager
    def _reporter(label, stream=None, min_interval=0.5):
        with real_reporter(label, stream=buf, min_interval=0.0) as report:
            yield report

    monkeypatch.setattr(regen, "progress_reporter", _reporter)
    monkeypatch.setattr(regen, "build_symbols_message", lambda folder, root: "msg")

    out = regen.generate_symbols(Path("pkg/sessions"), Path("pkg"),
                                 _StreamingClient(_DOC), "m")

    assert out.strip() == _DOC.strip()
    text = buf.getvalue()
    assert "SymbolMap: sessions" in text
    assert "lignes" in text
    # La progression AVANCE : la dernière ligne émise doit refléter les 20 lignes finales.
    assert "— 20 lignes" in text


def test_blocking_client_falls_back_without_crash(monkeypatch):
    monkeypatch.setattr(regen, "build_symbols_message", lambda folder, root: "msg")
    out = regen.generate_symbols(Path("pkg/sessions"), Path("pkg"),
                                 _BlockingClient(_DOC), "m")
    assert out.strip() == _DOC.strip()


def test_reporter_is_throttled():
    buf = io.StringIO()
    with progress_reporter("X", stream=buf, min_interval=10.0) as report:
        report("a\nb\nc\n")   # 1er appel : émet TOUJOURS (now monotonic >> last=0)
        time.sleep(0.01)
        report("a\nb\nc\nd\n")  # dans la même fenêtre de 10 s → throttlé (silencieux)
    # Seule la 1re ligne sort ; la 2e est throttlée.
    assert buf.getvalue() == "X — 3 lignes\n"


def test_reporter_emits_once_interval_elapsed():
    buf = io.StringIO()
    with progress_reporter("X", stream=buf, min_interval=0.0) as report:
        report("a\nb\n")
    assert "X — 2 lignes" in buf.getvalue()
