# [desc] chat/completions route: a stream kept alive without progress is aborted and replayed; a slow but progressing stream is not cut. [/desc]
"""Mesuré le 2026-10-05 (agent 9f14d1810dd5, tour 35) : flux gateway ouvert 296 s sans un token,
le délai de lecture de 180 s réarmé par chaque keep-alive. Le chien de garde de PROGRÈS
abandonne la tentative et la relance par la voie des erreurs en plein flux.

Faux serveur RÉEL (socket, chunked) : délais réduits à 1 s par la config."""
import pytest
import requests

from bouzecode.backend.agent.providers.backends.stream_progress import (
    StreamNoProgress, progress_timeouts,
)
from bouzecode.backend.agent.providers.types import AssistantTurn, StreamRestart
from tests.backend.providers.sse_script_server import SseScriptServer

MODULE = "bouzecode.backend.agent.providers.backends.openrouter_stream"
KEEP_ALIVE = ": keep-alive"
EMPTY_DELTA = 'data: {"choices":[{"delta":{}}]}'
FAST_WATCHDOG = {"stream_first_progress_timeout_s": 1, "stream_progress_timeout_s": 1}


def _token(text: str) -> str:
    return 'data: {"choices":[{"delta":{"content":"%s"}}]}' % text


GOOD = [(0, _token("Bonjour")),
        (0, 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":100,"completion_tokens":10}}'),
        (0, "data: [DONE]")]


def _alive_without_progress(seconds: float) -> list:
    """Keep-alives, blank lines and empty deltas every 0.2 s: the socket never idles."""
    filler = [KEEP_ALIVE, "", EMPTY_DELTA]
    return [(0.2, filler[i % 3]) for i in range(int(seconds / 0.2))]


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(f"{MODULE}._sleep", waited.append)
    return waited


def _direct_session():
    session = requests.Session()
    session.trust_env = False  # never route 127.0.0.1 through the corporate proxy
    return session


def _events(server: SseScriptServer, config: dict) -> list:
    from bouzecode.backend.agent.providers.backends.openrouter_stream import stream_openrouter
    return list(stream_openrouter(
        api_key="k-fake", model="claude-opus-5-5", system="sys",
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[], config=config,
        base_url=server.base_url, session_factory=_direct_session,
        send_reasoning=False, provider_label="gateway preprod",
    ))


def _final_text(events) -> str:
    return next(e for e in events if isinstance(e, AssistantTurn)).text


def test_keep_alives_without_a_token_abort_then_the_replay_succeeds(sleeps):
    with SseScriptServer([_alive_without_progress(4), GOOD]) as server:
        events = _events(server, FAST_WATCHDOG)
    assert len(server.request_bodies) == 2 and sleeps == [2.0]
    assert _final_text(events) == "Bonjour"
    # Le replay renvoie la requête octet pour octet : rien de notre fait ne casse le cache.
    assert server.request_bodies[0] == server.request_bodies[1]


def test_stall_after_text_restarts_the_turn(sleeps):
    stalled = [(0, _token("Bonj"))] + _alive_without_progress(4)
    with SseScriptServer([stalled, GOOD]) as server:
        events = _events(server, FAST_WATCHDOG)
    assert len(server.request_bodies) == 2
    assert any(isinstance(e, StreamRestart) for e in events)
    assert _final_text(events) == "Bonjour"


def test_slow_but_progressing_stream_is_not_cut(sleeps):
    slow = [(0.5, _token(f"t{i}")) for i in range(6)] + GOOD
    with SseScriptServer([slow]) as server:
        events = _events(server, FAST_WATCHDOG)
    assert len(server.request_bodies) == 1 and sleeps == []
    assert _final_text(events) == "t0t1t2t3t4t5Bonjour"


def test_stalls_beyond_the_replay_budget_fail_instead_of_hanging(sleeps):
    quick = {"stream_first_progress_timeout_s": 0.5, "stream_progress_timeout_s": 0.5}
    with SseScriptServer([_alive_without_progress(2)] * 3) as server:
        with pytest.raises(StreamNoProgress):
            _events(server, quick)
    assert len(server.request_bodies) == 3 and sleeps == [2.0, 8.0]


def test_timeouts_default_then_config_then_environment(monkeypatch):
    monkeypatch.delenv("BOUZECODE_STREAM_FIRST_PROGRESS_TIMEOUT_S", raising=False)
    monkeypatch.delenv("BOUZECODE_STREAM_PROGRESS_TIMEOUT_S", raising=False)
    assert progress_timeouts({}) == (60.0, 15.0)
    assert progress_timeouts(FAST_WATCHDOG) == (1.0, 1.0)
    monkeypatch.setenv("BOUZECODE_STREAM_FIRST_PROGRESS_TIMEOUT_S", "30")
    monkeypatch.setenv("BOUZECODE_STREAM_PROGRESS_TIMEOUT_S", "not-a-number")
    assert progress_timeouts(FAST_WATCHDOG) == (30.0, 1.0)
