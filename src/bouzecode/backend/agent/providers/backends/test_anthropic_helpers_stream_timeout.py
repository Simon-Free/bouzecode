"""Tests du garde-fou anti-flux-mort de `_iter_stream_resilient`.

Aucun mock : de vrais iterateurs sont construits, et les constantes de delai du
module sont monkeypatchees a des valeurs de l'ordre de 0.05s pour que la suite
reste rapide.
"""
from __future__ import annotations

import threading

import pytest

from bouzecode.backend.agent.providers.backends import anthropic_helpers as ah


class _MuteStream:
    """Flux qui ne delivre JAMAIS d'evenement (bloque jusqu'a liberation)."""

    def __init__(self, release: threading.Event) -> None:
        self._release = release

    def __iter__(self):
        return self

    def __next__(self):
        self._release.wait(30)
        raise StopIteration


class _ThenSilentStream:
    """Flux qui delivre `events` puis se tait (bloque jusqu'a liberation)."""

    def __init__(self, events, release: threading.Event) -> None:
        self._events = list(events)
        self._release = release

    def __iter__(self):
        return self

    def __next__(self):
        if self._events:
            return self._events.pop(0)
        self._release.wait(30)
        raise StopIteration


def _consume_in_thread(gen, out: list) -> threading.Thread:
    def _run():
        try:
            for ev in gen:
                out.append(("event", ev))
            out.append(("done", None))
        except BaseException as exc:  # noqa: BLE001 - on veut tout capturer
            out.append(("exc", exc))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


@pytest.fixture()
def fast_timeouts(monkeypatch):
    monkeypatch.setattr(ah, "_INTER_CHUNK_TIMEOUT_S", 0.05, raising=False)
    monkeypatch.setattr(ah, "_FIRST_EVENT_TIMEOUT_S", 0.05, raising=False)


def test_mute_stream_raises_stream_interrupted_about_first_event(fast_timeouts):
    """Un flux muet des le depart doit lever dans un delai BORNE."""
    release = threading.Event()
    warnings: list[str] = []
    out: list = []
    gen = ah._iter_stream_resilient(_MuteStream(release), warnings.append)
    t = _consume_in_thread(gen, out)
    try:
        t.join(timeout=3)
        assert not t.is_alive(), (
            "attente INFINIE sur le premier evenement : aucun _StreamInterrupted "
            "n'a ete leve en 3s"
        )
    finally:
        release.set()
        t.join(timeout=3)

    assert out and out[0][0] == "exc", f"attendu une exception, recu {out!r}"
    exc = out[0][1]
    assert isinstance(exc, ah._StreamInterrupted), repr(exc)
    assert "first" in str(exc).lower(), str(exc)
    assert warnings, "aucun warn() emis"
    assert "first" in warnings[0].lower(), warnings


def test_stream_going_silent_after_first_event_still_raises(fast_timeouts):
    """Non-regression : stall inter-chunk toujours detecte, message distinct."""
    release = threading.Event()
    warnings: list[str] = []
    out: list = []
    #  Le delai inter-chunk est un DEFAUT d'argument (fige a l'import, garde par
    #  test_inter_chunk_default_is_production_constant) : le patch du module ne l'atteint pas,
    #  il se passe par le parametre prevu pour les tests.
    gen = ah._iter_stream_resilient(
        _ThenSilentStream(["a", "b"], release), warnings.append, inter_chunk_timeout_s=0.05
    )
    t = _consume_in_thread(gen, out)
    try:
        t.join(timeout=3)
        assert not t.is_alive(), "stall inter-chunk non detecte en 3s"
    finally:
        release.set()
        t.join(timeout=3)

    assert [tag for tag, _ in out] == ["event", "event", "exc"], out
    assert [v for tag, v in out if tag == "event"] == ["a", "b"]
    exc = out[-1][1]
    assert isinstance(exc, ah._StreamInterrupted), repr(exc)
    assert "inter-chunk" in str(exc).lower(), str(exc)
    assert "first" not in str(exc).lower(), str(exc)


def test_complete_stream_yields_all_events_in_order(fast_timeouts):
    """Flux normal : aucun timeout, tous les evenements dans l'ordre."""
    events = ["e0", "e1", "e2", "e3"]
    warnings: list[str] = []
    out: list = []
    gen = ah._iter_stream_resilient(iter(events), warnings.append)
    t = _consume_in_thread(gen, out)
    t.join(timeout=3)
    assert not t.is_alive(), "le flux complet n'a pas termine"

    assert [tag for tag, _ in out] == ["event"] * 4 + ["done"], out
    assert [v for tag, v in out if tag == "event"] == events
    assert warnings == []
